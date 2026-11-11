use crate::tasks::{identifier, ActionRequest, TaskList, TaskView};
use crate::text::{validate_input, TextError, TextReply};
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use std::{
    io::{BufRead, BufReader, Read, Write},
    path::PathBuf,
    process::{Child, ChildStdin, Command, Stdio},
    sync::{mpsc, Mutex},
    thread,
    time::{Duration, Instant},
};

const MAX_TASK_RESPONSE_BYTES: u64 = 1_048_576;

#[derive(Clone, Debug, Serialize)]
pub struct BackendStatus {
    pub state: &'static str,
    pub error_code: Option<&'static str>,
}

impl BackendStatus {
    fn new(state: &'static str, error_code: Option<&'static str>) -> Self {
        Self { state, error_code }
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Handshake {
    protocol: u8,
    port: u16,
}

fn read_handshake(reader: impl Read) -> Result<u16, &'static str> {
    let mut line = String::new();
    BufReader::new(reader.take(4097))
        .read_line(&mut line)
        .map_err(|_| "BOOTSTRAP_INVALID")?;
    if line.len() > 4096 || !line.ends_with('\n') {
        return Err("BOOTSTRAP_INVALID");
    }
    let message: Handshake = serde_json::from_str(&line).map_err(|_| "BOOTSTRAP_INVALID")?;
    if message.protocol != 1 || message.port == 0 {
        return Err("BOOTSTRAP_INVALID");
    }
    Ok(message.port)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Health {
    api_version: String,
    app_version: String,
    status: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Readiness {
    api_version: String,
    status: String,
}

struct OwnedBackend {
    child: Child,
    input: Option<ChildStdin>,
    client: Client,
    port: u16,
    token: String, // Debug/Serialize uygulanmaz; frontend'e taşınmaz.
}

impl OwnedBackend {
    fn task_request<T: serde::de::DeserializeOwned>(
        &self,
        method: reqwest::Method,
        path: &str,
        body: Option<serde_json::Value>,
    ) -> Result<T, TextError> {
        self.api_request(method, &format!("/tasks{path}"), body)
    }

    fn api_request<T: serde::de::DeserializeOwned>(
        &self,
        method: reqwest::Method,
        path: &str,
        body: Option<serde_json::Value>,
    ) -> Result<T, TextError> {
        let mut request = self
            .client
            .request(
                method,
                format!("http://127.0.0.1:{}/api/v1{}", self.port, path),
            )
            .timeout(Duration::from_secs(15))
            .bearer_auth(&self.token);
        if let Some(body) = body {
            request = request.json(&body);
        }
        let response = request.send().map_err(|_| {
            TextError::local(
                "TASK_REQUEST_FAILED",
                "Görev isteği tamamlanamadı. Geçmişi yenileyin; yeni kimlikle tekrar göndermeyin.",
            )
        })?;
        let success = response.status().is_success();
        let mut bytes = Vec::new();
        response
            .take(MAX_TASK_RESPONSE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| TextError::contract())?;
        if bytes.len() as u64 > MAX_TASK_RESPONSE_BYTES {
            return Err(TextError::contract());
        }
        if !success {
            let error: TextError =
                serde_json::from_slice(&bytes).map_err(|_| TextError::contract())?;
            if error.error_code.len() > 64 || error.message.chars().count() > 512 {
                return Err(TextError::contract());
            }
            return Err(error);
        }
        serde_json::from_slice(&bytes).map_err(|_| TextError::contract())
    }
    fn process_text(&self, text: &str) -> Result<TextReply, TextError> {
        let response = self
            .client
            .post(format!("http://127.0.0.1:{}/api/v1/text", self.port))
            .bearer_auth(&self.token)
            .json(&serde_json::json!({"text": text}))
            .send()
            .map_err(|_| {
                TextError::local(
                    "BACKEND_REQUEST_FAILED",
                    "Metin backend'e iletilemedi. Lütfen yeniden deneyin.",
                )
            })?;
        let success = response.status().is_success();
        let mut body = Vec::new();
        response
            .take(16_385)
            .read_to_end(&mut body)
            .map_err(|_| TextError::contract())?;
        if body.len() > 16_384 {
            return Err(TextError::contract());
        }
        if !success {
            let error: TextError =
                serde_json::from_slice(&body).map_err(|_| TextError::contract())?;
            if error.error_code.len() > 64 || error.message.chars().count() > 512 {
                return Err(TextError::contract());
            }
            return Err(error);
        }
        serde_json::from_slice::<TextReply>(&body)
            .map_err(|_| TextError::contract())?
            .validate(text)
    }

    fn ready(&self) -> bool {
        let base = format!("http://127.0.0.1:{}", self.port);
        let health = self
            .client
            .get(format!("{base}/api/v1/health"))
            .bearer_auth(&self.token)
            .send()
            .and_then(|r| r.error_for_status())
            .and_then(|r| r.json::<Health>());
        let Ok(health) = health else {
            return false;
        };
        if health.api_version != "1" || health.app_version != "0.1.0" || health.status != "ok" {
            return false;
        }
        self.client
            .get(format!("{base}/api/v1/ready"))
            .bearer_auth(&self.token)
            .send()
            .and_then(|r| r.error_for_status())
            .and_then(|r| r.json::<Readiness>())
            .map(|r| r.api_version == "1" && r.status == "ready")
            .unwrap_or(false)
    }

    fn stop(&mut self) {
        if let Some(mut input) = self.input.take() {
            let _ = input.write_all(b"shutdown\n");
            let _ = input.flush();
            // Pipe kapanışı da child'ın EOF izlemesini tetikler.
        }
        let deadline = Instant::now() + Duration::from_secs(3);
        while Instant::now() < deadline {
            if matches!(self.child.try_wait(), Ok(Some(_))) {
                return;
            }
            thread::sleep(Duration::from_millis(30));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

impl Drop for OwnedBackend {
    fn drop(&mut self) {
        self.stop();
    }
}

pub struct Supervisor {
    backend: Mutex<Option<OwnedBackend>>,
    status: Mutex<BackendStatus>,
}

impl Supervisor {
    pub fn create_windows_task(&self, action: &ActionRequest) -> Result<TaskView, TextError> {
        action.validate()?;
        if action.simulated() {
            return Err(TextError::contract());
        }
        self.windows_call(
            reqwest::Method::POST,
            "/windows/tasks",
            Some(serde_json::to_value(action).map_err(|_| TextError::contract())?),
            Some(action.task_id()),
        )
    }
    pub fn submit_windows_command(
        &self,
        task_id: &str,
        action_id: &str,
        text: &str,
    ) -> Result<TaskView, TextError> {
        identifier(task_id)?;
        identifier(action_id)?;
        validate_input(text)?;
        self.windows_call(
            reqwest::Method::POST,
            "/windows/commands",
            Some(serde_json::json!({"task_id":task_id,"action_id":action_id,"text":text})),
            Some(task_id),
        )
    }
    pub fn list_windows_tasks(&self) -> Result<TaskList, TextError> {
        let slot = self.backend.lock().map_err(|_| TextError::contract())?;
        let backend = slot
            .as_ref()
            .ok_or_else(|| TextError::local("BACKEND_UNAVAILABLE", "Backend'e bağlanılamadı."))?;
        let reply: TaskList = backend.api_request(reqwest::Method::GET, "/windows/tasks", None)?;
        if reply.tasks.len() > 20 {
            return Err(TextError::contract());
        }
        for task in &reply.tasks {
            task.validate()?;
            if task.simulated {
                return Err(TextError::contract());
            }
        }
        Ok(reply)
    }
    fn windows_call(
        &self,
        method: reqwest::Method,
        path: &str,
        body: Option<serde_json::Value>,
        id: Option<&str>,
    ) -> Result<TaskView, TextError> {
        let slot = self.backend.lock().map_err(|_| TextError::contract())?;
        let backend = slot
            .as_ref()
            .ok_or_else(|| TextError::local("BACKEND_UNAVAILABLE", "Backend'e bağlanılamadı."))?;
        let reply: TaskView = backend.api_request(method, path, body)?;
        reply.validate()?;
        if reply.simulated || id.is_some_and(|id| reply.action.task_id() != id) {
            return Err(TextError::contract());
        }
        Ok(reply)
    }
    pub fn windows_operation(
        &self,
        task_id: &str,
        approval: Option<(&str, bool)>,
        cancel: bool,
    ) -> Result<TaskView, TextError> {
        identifier(task_id)?;
        let (suffix, body) = if let Some((id, approve)) = approval {
            identifier(id)?;
            (
                "/approval",
                Some(serde_json::json!({"approval_id":id,"approve":approve,"source":"screen"})),
            )
        } else if cancel {
            ("/cancel", None)
        } else {
            return Err(TextError::contract());
        };
        self.windows_call(
            reqwest::Method::POST,
            &format!("/windows/tasks/{task_id}{suffix}"),
            body,
            Some(task_id),
        )
    }
    pub fn create_task(&self, action: &ActionRequest) -> Result<TaskView, TextError> {
        action.validate()?;
        if !action.simulated() {
            return Err(TextError::contract());
        }
        let slot = self.backend.lock().map_err(|_| TextError::contract())?;
        let backend = slot
            .as_ref()
            .ok_or_else(|| TextError::local("BACKEND_UNAVAILABLE", "Backend'e bağlanılamadı."))?;
        let reply: TaskView = backend.task_request(
            reqwest::Method::POST,
            "",
            Some(serde_json::to_value(action).map_err(|_| TextError::contract())?),
        )?;
        reply.validate()?;
        if reply.action != *action {
            return Err(TextError::contract());
        }
        Ok(reply)
    }
    pub fn list_tasks(&self) -> Result<TaskList, TextError> {
        let slot = self.backend.lock().map_err(|_| TextError::contract())?;
        let backend = slot
            .as_ref()
            .ok_or_else(|| TextError::local("BACKEND_UNAVAILABLE", "Backend'e bağlanılamadı."))?;
        let reply: TaskList = backend.task_request(reqwest::Method::GET, "", None)?;
        if reply.tasks.len() > 20 {
            return Err(TextError::contract());
        }
        for task in &reply.tasks {
            task.validate()?;
        }
        Ok(reply)
    }
    pub fn task_operation(
        &self,
        task_id: &str,
        operation: &str,
        approval: Option<(&str, bool)>,
    ) -> Result<TaskView, TextError> {
        identifier(task_id)?;
        let (method, suffix, body) = match operation {
            "view" => (reqwest::Method::GET, "", None),
            "cancel" => (reqwest::Method::POST, "/cancel", None),
            "reconcile" => (reqwest::Method::POST, "/reconcile", None),
            "approval" => {
                let (id, approve) = approval.ok_or_else(TextError::contract)?;
                identifier(id)?;
                (
                    reqwest::Method::POST,
                    "/approval",
                    Some(serde_json::json!({"approval_id":id,"approve":approve,"source":"screen"})),
                )
            }
            _ => return Err(TextError::contract()),
        };
        let slot = self.backend.lock().map_err(|_| TextError::contract())?;
        let backend = slot
            .as_ref()
            .ok_or_else(|| TextError::local("BACKEND_UNAVAILABLE", "Backend'e bağlanılamadı."))?;
        let reply: TaskView = backend.task_request(method, &format!("/{task_id}{suffix}"), body)?;
        reply.validate()?;
        if reply.action.task_id() != task_id {
            return Err(TextError::contract());
        }
        Ok(reply)
    }
    pub fn new() -> Self {
        Self {
            backend: Mutex::new(None),
            status: Mutex::new(BackendStatus::new("connecting", None)),
        }
    }

    fn publish(&self, state: &'static str, error_code: Option<&'static str>) -> BackendStatus {
        let next = BackendStatus::new(state, error_code);
        *self.status.lock().unwrap_or_else(|e| e.into_inner()) = next.clone();
        next
    }

    fn snapshot(&self) -> BackendStatus {
        self.status
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone()
    }

    pub fn start(&self, reconnect: bool) -> BackendStatus {
        // Başlatma/restart/stop aynı child sahipliği kilidinden geçer.
        let mut slot = if reconnect {
            match self.backend.try_lock() {
                Ok(slot) => slot,
                Err(_) => return BackendStatus::new("failed", Some("HOST_BUSY")),
            }
        } else {
            // İlk başlangıç, kısa süreli bir status sorgusu yüzünden atlanamaz.
            self.backend.lock().unwrap_or_else(|e| e.into_inner())
        };
        self.publish(
            if reconnect {
                "reconnecting"
            } else {
                "connecting"
            },
            None,
        );
        drop(slot.take());
        match launch_backend(Duration::from_secs(45)) {
            Ok(child) => {
                *slot = Some(child);
                self.publish("ready", None)
            }
            Err(code) => self.publish("failed", Some(code)),
        }
    }

    pub fn inspect(&self) -> BackendStatus {
        let Ok(mut slot) = self.backend.try_lock() else {
            return self.snapshot();
        };
        let Some(backend) = slot.as_mut() else {
            return self.snapshot();
        };
        let error = match backend.child.try_wait() {
            Ok(Some(_)) | Err(_) => Some("BACKEND_EXITED"),
            Ok(None) if !backend.ready() => Some("BACKEND_UNREACHABLE"),
            Ok(None) => None,
        };
        if let Some(code) = error {
            drop(slot.take());
            return self.publish("failed", Some(code));
        }
        self.snapshot()
    }

    pub fn stop(&self) {
        let mut slot = self.backend.lock().unwrap_or_else(|e| e.into_inner());
        drop(slot.take());
    }

    pub fn process_text(&self, text: &str) -> Result<TextReply, TextError> {
        validate_input(text)?;
        let slot = self.backend.lock().map_err(|_| {
            TextError::local("HOST_UNAVAILABLE", "Masaüstü bağlantısı kullanılamıyor.")
        })?;
        let backend = slot.as_ref().ok_or_else(|| {
            TextError::local(
                "BACKEND_UNAVAILABLE",
                "Backend'e bağlanılamadı. Önce yeniden bağlanın.",
            )
        })?;
        backend.process_text(text)
    }
}

fn launch_backend(timeout: Duration) -> Result<OwnedBackend, &'static str> {
    if !cfg!(debug_assertions) {
        return Err("DEV_BACKEND_ONLY");
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let python = base_python(&root)?;
    if !python.is_file() {
        return Err("PYTHON_UNAVAILABLE");
    }
    let mut entropy = [0_u8; 32];
    getrandom::fill(&mut entropy).map_err(|_| "ENTROPY_UNAVAILABLE")?;
    let token: String = entropy.iter().map(|b| format!("{b:02x}")).collect();
    let client = Client::builder()
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .connect_timeout(Duration::from_millis(200))
        .timeout(Duration::from_millis(500))
        .build()
        .map_err(|_| "CLIENT_INIT_FAILED")?;
    let mut command = Command::new(python);
    command
        .args(["-I", "-S", "-u"])
        .arg(root.join("scripts/dev_backend.py"))
        .current_dir(&root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }
    launch_command(command, client, token, timeout)
}

fn base_python(root: &std::path::Path) -> Result<PathBuf, &'static str> {
    let config =
        std::fs::read_to_string(root.join(".venv/pyvenv.cfg")).map_err(|_| "PYTHON_UNAVAILABLE")?;
    config
        .lines()
        .find_map(|line| line.strip_prefix("executable = "))
        .map(|value| PathBuf::from(value.trim()))
        .filter(|path| path.is_absolute() && path.is_file())
        .ok_or("PYTHON_UNAVAILABLE")
}

fn launch_command(
    mut command: Command,
    client: Client,
    token: String,
    timeout: Duration,
) -> Result<OwnedBackend, &'static str> {
    let child = command.spawn().map_err(|_| "BACKEND_START_FAILED")?;
    let mut owned = OwnedBackend {
        child,
        input: None,
        client,
        port: 0,
        token,
    };
    owned.input = owned.child.stdin.take();
    let stdout = owned.child.stdout.take().ok_or("BOOTSTRAP_INVALID")?;
    let deadline = Instant::now() + timeout;
    let bootstrap = serde_json::json!({ "protocol": 1, "token": owned.token });
    let input = owned.input.as_mut().ok_or("BOOTSTRAP_INVALID")?;
    writeln!(input, "{bootstrap}").map_err(|_| "BOOTSTRAP_FAILED")?;
    input.flush().map_err(|_| "BOOTSTRAP_FAILED")?;
    let (sender, receiver) = mpsc::sync_channel(1);
    thread::spawn(move || {
        let _ = sender.send(read_handshake(stdout));
    });
    owned.port = receiver
        .recv_timeout(timeout)
        .map_err(|_| "STARTUP_TIMEOUT")??;
    loop {
        if owned
            .child
            .try_wait()
            .map_err(|_| "BACKEND_EXITED")?
            .is_some()
        {
            return Err("BACKEND_EXITED");
        }
        if Instant::now() >= deadline {
            return Err("STARTUP_TIMEOUT");
        }
        if owned.ready() {
            if Instant::now() >= deadline {
                return Err("STARTUP_TIMEOUT");
            }
            return Ok(owned);
        }
        thread::sleep(Duration::from_millis(50));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bounded_unicode_file_history_fits_task_transport_limit() {
        let id = "00000000-0000-0000-0000-000000000001";
        let file = serde_json::json!({"root_id":"test","relative_path":format!("{}.txt","漢".repeat(170)),"identity":"a".repeat(64),"size":10});
        let task = serde_json::json!({"api_version":"1","simulated":false,"external_calls":0,
            "action":{"task_id":id,"action_id":id,"tool_id":"windows.search_files","arguments":{"root_id":"test","query":"漢"},"scope":"windows.files"},
            "status":"succeeded","error_code":null,"approval":null,
            "result":{"status":"succeeded","message":"Metadata araması tamamlandı.","simulated":false,"details":{"completion":"metadata_search","process_id":null,"files":vec![file;20],"truncated":true}},
            "events":[{"sequence":1,"kind":"execution_result","status":"succeeded","created_at":1.0}]});
        let value = serde_json::json!({"tasks":vec![task;20]});
        let bytes = serde_json::to_vec(&value).unwrap();
        assert!(bytes.len() > 262_144);
        assert!((bytes.len() as u64) < MAX_TASK_RESPONSE_BYTES);
        let list: TaskList = serde_json::from_slice(&bytes).unwrap();
        for task in list.tasks {
            task.validate().unwrap();
        }
    }

    #[test]
    fn task_ipc_uses_real_backend_approval_and_persistent_results() {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let data = std::env::temp_dir().join(format!("nova-task-ipc-{nonce}"));
        let mut command = Command::new(base_python(&root).unwrap());
        command
            .args(["-I", "-S", "-u"])
            .arg(root.join("scripts/dev_backend.py"))
            .env("NOVA_TASK_DATA_DIR", &data)
            .env_remove("NOVA_WINDOWS_TOOLS_CONFIG")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        let client = Client::builder()
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .timeout(Duration::from_millis(500))
            .build()
            .unwrap();
        let backend =
            launch_command(command, client, "b".repeat(64), Duration::from_secs(45)).unwrap();
        let supervisor = Supervisor::new();
        *supervisor.backend.lock().unwrap() = Some(backend);
        let action:ActionRequest=serde_json::from_value(serde_json::json!({
            "task_id":"00000000-0000-0000-0000-000000000001","action_id":"00000000-0000-0000-0000-000000000002",
            "tool_id":"fake.open_app","arguments":{"app_id":"demo.editor"},"scope":"simulation.apps"})).unwrap();
        let pending = supervisor.create_task(&action).unwrap();
        assert_eq!(pending.status, crate::tasks::TaskStatus::AwaitingApproval);
        let approval = pending.approval.unwrap().approval_id;
        let result = supervisor
            .task_operation(action.task_id(), "approval", Some((&approval, true)))
            .unwrap();
        assert_eq!(result.status, crate::tasks::TaskStatus::Succeeded);
        assert!(result.result.unwrap().simulated);
        assert_eq!(
            supervisor
                .task_operation(action.task_id(), "approval", Some((&approval, true)))
                .unwrap_err()
                .error_code,
            "APPROVAL_REPLAY"
        );
        assert_eq!(supervisor.list_tasks().unwrap().tasks.len(), 1);
        let real:ActionRequest=serde_json::from_value(serde_json::json!({
            "task_id":"00000000-0000-0000-0000-000000000004","action_id":"00000000-0000-0000-0000-000000000005",
            "tool_id":"windows.open_app","arguments":{"app_id":"windows.notepad"},"scope":"windows.apps"})).unwrap();
        assert!(supervisor.create_task(&real).is_err());
        let denied = supervisor.create_windows_task(&real).unwrap();
        assert_eq!(denied.status, crate::tasks::TaskStatus::Failed);
        assert_eq!(denied.error_code.as_deref(), Some("PERMISSION_DENIED"));
        assert!(!denied.simulated);
        assert_eq!(supervisor.list_windows_tasks().unwrap().tasks.len(), 1);
        assert_eq!(
            supervisor
                .submit_windows_command(
                    "00000000-0000-0000-0000-000000000006",
                    "00000000-0000-0000-0000-000000000007",
                    "Chrome'u aç"
                )
                .unwrap_err()
                .error_code,
            "APP_NOT_ALLOWED"
        );
        assert!(supervisor
            .task_operation("../../bad", "view", None)
            .is_err());
        supervisor.stop();
        assert!(data.starts_with(std::env::temp_dir()));
        std::fs::remove_dir_all(data).unwrap();
    }

    #[test]
    fn handshake_rejects_bad_protocol_port_and_extra_fields() {
        assert_eq!(
            read_handshake(b"{\"protocol\":1,\"port\":43210}\n".as_slice()),
            Ok(43210)
        );
        for invalid in [
            "{\"protocol\":2,\"port\":1}\n",
            "{\"protocol\":1,\"port\":0}\n",
            "{\"protocol\":1,\"port\":1,\"token\":\"secret\"}\n",
            "not json\n",
        ] {
            assert!(read_handshake(invalid.as_bytes()).is_err());
        }
        assert!(read_handshake("x".repeat(5000).as_bytes()).is_err());
    }

    #[test]
    fn status_contract_has_no_secrets_or_addresses() {
        let value =
            serde_json::to_value(BackendStatus::new("failed", Some("STARTUP_TIMEOUT"))).unwrap();
        assert_eq!(
            value,
            serde_json::json!({"state":"failed","error_code":"STARTUP_TIMEOUT"})
        );
    }

    fn test_command(code: &str) -> Command {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
        let mut command = Command::new(base_python(&root).unwrap());
        command
            .args(["-I", "-S", "-u", "-c", code])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        command
    }

    #[test]
    fn startup_timeout_releases_owned_process_socket() {
        use std::net::{TcpListener, TcpStream};
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        drop(listener);
        let code = format!(
            "import socket,sys,json; sys.stdin.readline(); s=socket.socket(); s.bind(('127.0.0.1',{})); s.listen(); print(json.dumps({{'protocol':1,'port':{}}}),flush=True); sys.stdin.readline()",
            address.port(), address.port()
        );
        let client = Client::builder()
            .no_proxy()
            .timeout(Duration::from_millis(100))
            .build()
            .unwrap();
        let result = launch_command(
            test_command(&code),
            client,
            "a".repeat(64),
            Duration::from_millis(500),
        );
        assert!(matches!(result, Err("STARTUP_TIMEOUT")));
        assert!(TcpStream::connect_timeout(&address, Duration::from_millis(100)).is_err());
    }

    #[test]
    fn unexpected_exit_is_reported_without_exposing_child_output() {
        let code = "import sys; sys.stdin.readline(); print('process detail',flush=True)";
        let client = Client::builder()
            .no_proxy()
            .timeout(Duration::from_millis(100))
            .build()
            .unwrap();
        let result = launch_command(
            test_command(code),
            client,
            "a".repeat(64),
            Duration::from_secs(2),
        );
        assert!(matches!(result, Err("BOOTSTRAP_INVALID")));
    }

    #[test]
    fn real_backend_exit_changes_supervisor_status() {
        let mut backend =
            launch_backend(Duration::from_secs(45)).expect("Test backend'i başlamalı");
        backend.child.kill().unwrap();
        backend.child.wait().unwrap();
        let supervisor = Supervisor::new();
        *supervisor.backend.lock().unwrap() = Some(backend);
        supervisor.publish("ready", None);
        let status = supervisor.inspect();
        assert_eq!(status.state, "failed");
        assert_eq!(status.error_code, Some("BACKEND_EXITED"));
        assert!(supervisor.backend.lock().unwrap().is_none());
    }

    #[test]
    fn real_backend_graceful_stop_releases_port() {
        use std::net::{SocketAddr, TcpStream};
        let mut backend =
            launch_backend(Duration::from_secs(45)).expect("Test backend'i başlamalı");
        let address: SocketAddr = format!("127.0.0.1:{}", backend.port).parse().unwrap();
        assert!(backend.ready());
        backend.stop();
        assert!(backend.child.try_wait().unwrap().is_some());
        assert!(TcpStream::connect_timeout(&address, Duration::from_millis(100)).is_err());
    }

    #[test]
    fn initial_start_waits_for_concurrent_status_lock() {
        let supervisor = std::sync::Arc::new(Supervisor::new());
        let status_lock = supervisor.backend.lock().unwrap();
        let worker = supervisor.clone();
        let (entered_tx, entered_rx) = mpsc::channel();
        let (result_tx, result_rx) = mpsc::channel();
        let handle = thread::spawn(move || {
            entered_tx.send(()).unwrap();
            result_tx.send(worker.start(false)).unwrap();
        });
        entered_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        assert!(matches!(
            result_rx.recv_timeout(Duration::from_millis(200)),
            Err(mpsc::RecvTimeoutError::Timeout)
        ));
        drop(status_lock);
        let result = result_rx.recv_timeout(Duration::from_secs(50)).unwrap();
        assert_eq!(result.state, "ready");
        handle.join().unwrap();
        supervisor.stop();
    }

    #[test]
    fn text_ipc_service_uses_real_authenticated_backend_without_actions() {
        let supervisor = Supervisor::new();
        assert_eq!(
            supervisor.process_text("2+2").unwrap_err().error_code,
            "BACKEND_UNAVAILABLE"
        );
        assert_eq!(supervisor.start(false).state, "ready");
        let result = supervisor.process_text("2 + 2 kaç?").unwrap();
        assert_eq!(result.reply, "Dört.");
        assert_eq!(result.intent, crate::text::Intent::Arithmetic);
        assert_eq!(
            supervisor.process_text("1/0").unwrap_err().error_code,
            "ARITHMETIC_DIVISION_BY_ZERO"
        );
        let action = supervisor.process_text("Chrome'u aç").unwrap();
        assert!(!action.action.unwrap().executable);
        assert_eq!(
            supervisor.process_text("Python nedir?").unwrap().intent,
            crate::text::Intent::GeneralChat
        );
        assert_eq!(supervisor.inspect().state, "ready");
        supervisor.stop();
    }
}
