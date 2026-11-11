use crate::text::TextError;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OpenArguments {
    pub app_id: String,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SearchArguments {
    pub query: String,
    pub root_id: String,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileArguments {
    pub root_id: String,
    pub relative_path: String,
    pub identity: String,
}
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct WebArguments {
    pub query: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "tool_id", deny_unknown_fields)]
pub enum ActionRequest {
    #[serde(rename = "windows.open_app")]
    WindowsOpen {
        task_id: String,
        action_id: String,
        arguments: OpenArguments,
        scope: String,
    },
    #[serde(rename = "windows.search_files")]
    WindowsSearch {
        task_id: String,
        action_id: String,
        arguments: SearchArguments,
        scope: String,
    },
    #[serde(rename = "windows.open_file")]
    WindowsFile {
        task_id: String,
        action_id: String,
        arguments: FileArguments,
        scope: String,
    },
    #[serde(rename = "windows.web_search")]
    WindowsWeb {
        task_id: String,
        action_id: String,
        arguments: WebArguments,
        scope: String,
    },
    #[serde(rename = "fake.open_app")]
    Open {
        task_id: String,
        action_id: String,
        arguments: OpenArguments,
        scope: String,
    },
    #[serde(rename = "fake.search_files")]
    Search {
        task_id: String,
        action_id: String,
        arguments: SearchArguments,
        scope: String,
    },
}

pub fn identifier(value: &str) -> Result<(), TextError> {
    if value.len() != 36
        || !value.bytes().enumerate().all(|(i, b)| {
            if [8, 13, 18, 23].contains(&i) {
                b == b'-'
            } else {
                b.is_ascii_digit() || (b'a'..=b'f').contains(&b)
            }
        })
    {
        return Err(TextError::local(
            "INVALID_ACTION",
            "Görev veya eylem kimliği geçersiz.",
        ));
    }
    Ok(())
}

impl ActionRequest {
    pub fn simulated(&self) -> bool {
        matches!(self, Self::Open { .. } | Self::Search { .. })
    }
    pub fn task_id(&self) -> &str {
        match self {
            Self::Open { task_id, .. }
            | Self::Search { task_id, .. }
            | Self::WindowsOpen { task_id, .. }
            | Self::WindowsSearch { task_id, .. }
            | Self::WindowsFile { task_id, .. }
            | Self::WindowsWeb { task_id, .. } => task_id,
        }
    }
    pub fn validate(&self) -> Result<(), TextError> {
        let (task, action, valid) = match self {
            Self::WindowsOpen {
                task_id,
                action_id,
                arguments,
                scope,
            } => (
                task_id,
                action_id,
                arguments.app_id == "windows.notepad" && scope == "windows.apps",
            ),
            Self::WindowsSearch {
                task_id,
                action_id,
                arguments,
                scope,
            } => (
                task_id,
                action_id,
                root_id(&arguments.root_id)
                    && !arguments.query.trim().is_empty()
                    && arguments.query.chars().count() <= 64
                    && scope == "windows.files",
            ),
            Self::WindowsFile {
                task_id,
                action_id,
                arguments,
                scope,
            } => (
                task_id,
                action_id,
                root_id(&arguments.root_id)
                    && safe_file(&arguments.relative_path)
                    && hex_id(&arguments.identity)
                    && scope == "windows.files",
            ),
            Self::WindowsWeb {
                task_id,
                action_id,
                arguments,
                scope,
            } => (
                task_id,
                action_id,
                !arguments.query.trim().is_empty()
                    && arguments.query.chars().count() <= 256
                    && !arguments.query.contains([':', '\\'])
                    && !arguments.query.chars().any(char::is_control)
                    && scope == "windows.web",
            ),
            Self::Open {
                task_id,
                action_id,
                arguments,
                scope,
            } => (
                task_id,
                action_id,
                ["demo.editor", "demo.admin"].contains(&arguments.app_id.as_str())
                    && scope == "simulation.apps",
            ),
            Self::Search {
                task_id,
                action_id,
                arguments,
                scope,
            } => (
                task_id,
                action_id,
                ["ornek", "rapor"].contains(&arguments.query.as_str())
                    && arguments.root_id == "synthetic.documents"
                    && scope == "simulation.files",
            ),
        };
        identifier(task)?;
        identifier(action)?;
        if !valid {
            return Err(TextError::local(
                "INVALID_ACTION",
                "Yalnızca kayıtlı simülasyon argümanları kabul edilir.",
            ));
        }
        Ok(())
    }
}

#[derive(Debug, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskStatus {
    Queued,
    Running,
    AwaitingApproval,
    Succeeded,
    Failed,
    Cancelled,
    Unknown,
}

fn root_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 32
        && value
            .bytes()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || b"_-".contains(&c))
}
fn hex_id(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c))
}
fn safe_file(value: &str) -> bool {
    !value.is_empty()
        && value.chars().count() <= 180
        && !value.contains([':', '\\'])
        && value
            .split('/')
            .all(|p| !p.is_empty() && p != "." && p != ".." && !p.starts_with('.'))
        && value.to_lowercase().ends_with(".txt")
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ApprovalView {
    pub approval_id: String,
    pub action: ActionRequest,
    pub risk: String,
    pub expected_effect: String,
    pub expires_at: f64,
    pub policy_version: String,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionResult {
    pub status: TaskStatus,
    pub message: String,
    pub simulated: bool,
    pub details: Option<ToolDetails>,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileMatch {
    pub root_id: String,
    pub relative_path: String,
    pub identity: String,
    pub size: u64,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Completion {
    ProcessStarted,
    HandoffRequested,
    MetadataSearch,
    SearchSubmitted,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ToolDetails {
    pub completion: Completion,
    pub process_id: Option<u32>,
    pub files: Vec<FileMatch>,
    pub truncated: bool,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TaskEvent {
    pub sequence: u32,
    pub kind: String,
    pub status: TaskStatus,
    pub created_at: f64,
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TaskView {
    pub api_version: String,
    pub simulated: bool,
    pub external_calls: u8,
    pub action: ActionRequest,
    pub status: TaskStatus,
    pub result: Option<ExecutionResult>,
    pub error_code: Option<String>,
    pub approval: Option<ApprovalView>,
    pub events: Vec<TaskEvent>,
}
impl TaskView {
    pub fn validate(&self) -> Result<(), TextError> {
        self.action.validate()?;
        let bad = self.api_version != "1"
            || self.simulated != self.action.simulated()
            || self.external_calls != 0
            || self.events.is_empty()
            || self.events.len() > 64
            || self.events.iter().enumerate().any(|(i, e)| {
                e.sequence as usize != i + 1 || e.kind.len() > 64 || !e.created_at.is_finite()
            })
            || self.error_code.as_ref().is_some_and(|v| v.len() > 64)
            || self.result.as_ref().is_some_and(|r| {
                r.simulated != self.simulated
                    || r.message.chars().count() > 512
                    || r.status != self.status
                    || !matches!(r.status, TaskStatus::Succeeded | TaskStatus::Failed)
                    || r.details.as_ref().is_some_and(|d| {
                        d.files.len() > 20
                            || d.files.iter().any(|f| {
                                !root_id(&f.root_id)
                                    || !safe_file(&f.relative_path)
                                    || !hex_id(&f.identity)
                                    || f.size > 10 * 1024 * 1024
                            })
                    })
            })
            || (self.status == TaskStatus::Succeeded && self.result.is_none())
            || self.approval.as_ref().is_some_and(|a| {
                identifier(&a.approval_id).is_err()
                    || a.action != self.action
                    || a.risk != "high"
                    || !a.expires_at.is_finite()
                    || a.expected_effect.chars().count() > 512
                    || a.policy_version.len() > 64
                    || self.status != TaskStatus::AwaitingApproval
            });
        if bad {
            return Err(TextError::contract());
        }
        Ok(())
    }
}
#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TaskList {
    pub tasks: Vec<TaskView>,
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn only_registered_fake_typed_actions_cross_ipc() {
        let id = "00000000-0000-0000-0000-000000000001";
        let valid = serde_json::json!({"task_id":id,"action_id":id,"tool_id":"fake.open_app","scope":"simulation.apps","arguments":{"app_id":"demo.editor"}});
        let a: ActionRequest = serde_json::from_value(valid.clone()).unwrap();
        assert!(a.validate().is_ok());
        for tool in ["windows.unregistered_app", "shell", "fake.unknown"] {
            let mut v = valid.clone();
            v["tool_id"] = serde_json::json!(tool);
            assert!(serde_json::from_value::<ActionRequest>(v).is_err());
        }
        let mut v = valid;
        v["arguments"]["app_id"] = serde_json::json!("C:/Windows/cmd.exe");
        assert!(serde_json::from_value::<ActionRequest>(v)
            .unwrap()
            .validate()
            .is_err());
        assert!(identifier("../../private").is_err());
    }

    #[test]
    fn registered_windows_contract_rejects_paths_and_scope_injection() {
        let id = "00000000-0000-0000-0000-000000000001";
        let value = serde_json::json!({"task_id":id,"action_id":id,"tool_id":"windows.open_app","arguments":{"app_id":"windows.notepad"},"scope":"windows.apps"});
        let good: ActionRequest = serde_json::from_value(value.clone()).unwrap();
        assert!(good.validate().is_ok());
        assert!(!good.simulated());
        for app in [
            "demo.editor",
            "cmd.exe",
            "C:/Windows/notepad.exe",
            "windows.notepad --evil",
        ] {
            let mut bad = value.clone();
            bad["arguments"]["app_id"] = serde_json::json!(app);
            assert!(serde_json::from_value::<ActionRequest>(bad)
                .unwrap()
                .validate()
                .is_err());
        }
        let mut bad = value;
        bad["scope"] = serde_json::json!("host.all");
        assert!(serde_json::from_value::<ActionRequest>(bad)
            .unwrap()
            .validate()
            .is_err());
    }

    #[test]
    fn windows_file_and_browser_inputs_have_no_arbitrary_uri_bridge() {
        assert!(!safe_file("../rapor.txt"));
        assert!(!safe_file("C:/rapor.txt"));
        assert!(!safe_file("a.txt:evil"));
        let id = "00000000-0000-0000-0000-000000000001";
        for query in [
            "file:C:/a",
            "javascript:alert(1)",
            "https://evil.example",
            "bad\nquery",
        ] {
            let a = ActionRequest::WindowsWeb {
                task_id: id.into(),
                action_id: id.into(),
                arguments: WebArguments {
                    query: query.into(),
                },
                scope: "windows.web".into(),
            };
            assert!(a.validate().is_err());
        }
    }
}
