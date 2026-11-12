#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend;
mod chat;
mod tasks;
mod text;
use backend::{BackendStatus, Supervisor};
use std::sync::Arc;
use tauri::Manager;

#[tauri::command]
async fn backend_status(
    state: tauri::State<'_, Arc<Supervisor>>,
) -> Result<BackendStatus, &'static str> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || supervisor.inspect())
        .await
        .map_err(|_| "HOST_UNAVAILABLE")
}

#[tauri::command]
async fn backend_restart(
    state: tauri::State<'_, Arc<Supervisor>>,
) -> Result<BackendStatus, &'static str> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || supervisor.start(true))
        .await
        .map_err(|_| "HOST_UNAVAILABLE")
}

#[tauri::command]
async fn process_text(
    state: tauri::State<'_, Arc<Supervisor>>,
    text: String,
) -> Result<text::TextReply, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || supervisor.process_text(&text))
        .await
        .map_err(|_| {
            text::TextError::local("HOST_UNAVAILABLE", "Masaüstü bağlantısı kullanılamıyor.")
        })?
}

#[tauri::command]
async fn create_simulated_task(
    state: tauri::State<'_, Arc<Supervisor>>,
    action: tasks::ActionRequest,
) -> Result<tasks::TaskView, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || supervisor.create_task(&action))
        .await
        .map_err(|_| {
            text::TextError::local("HOST_UNAVAILABLE", "Masaüstü bağlantısı kullanılamıyor.")
        })?
}

#[tauri::command]
async fn list_simulated_tasks(
    state: tauri::State<'_, Arc<Supervisor>>,
) -> Result<tasks::TaskList, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || supervisor.list_tasks())
        .await
        .map_err(|_| {
            text::TextError::local("HOST_UNAVAILABLE", "Masaüstü bağlantısı kullanılamıyor.")
        })?
}

#[tauri::command]
async fn get_simulated_task(
    state: tauri::State<'_, Arc<Supervisor>>,
    task_id: String,
) -> Result<tasks::TaskView, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || supervisor.task_operation(&task_id, "view", None))
        .await
        .map_err(|_| {
            text::TextError::local("HOST_UNAVAILABLE", "Masaüstü bağlantısı kullanılamıyor.")
        })?
}

#[tauri::command]
async fn decide_simulated_approval(
    state: tauri::State<'_, Arc<Supervisor>>,
    task_id: String,
    approval_id: String,
    approve: bool,
) -> Result<tasks::TaskView, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        supervisor.task_operation(&task_id, "approval", Some((&approval_id, approve)))
    })
    .await
    .map_err(|_| {
        text::TextError::local("HOST_UNAVAILABLE", "Masaüstü bağlantısı kullanılamıyor.")
    })?
}

#[tauri::command]
async fn cancel_simulated_task(
    state: tauri::State<'_, Arc<Supervisor>>,
    task_id: String,
) -> Result<tasks::TaskView, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        supervisor.task_operation(&task_id, "cancel", None)
    })
    .await
    .map_err(|_| {
        text::TextError::local("HOST_UNAVAILABLE", "Masaüstü bağlantısı kullanılamıyor.")
    })?
}

#[tauri::command]
async fn reconcile_simulated_task(
    state: tauri::State<'_, Arc<Supervisor>>,
    task_id: String,
) -> Result<tasks::TaskView, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        supervisor.task_operation(&task_id, "reconcile", None)
    })
    .await
    .map_err(|_| {
        text::TextError::local("HOST_UNAVAILABLE", "Masaüstü bağlantısı kullanılamıyor.")
    })?
}

#[tauri::command]
async fn create_windows_task(
    state: tauri::State<'_, Arc<Supervisor>>,
    action: tasks::ActionRequest,
) -> Result<tasks::TaskView, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || supervisor.create_windows_task(&action))
        .await
        .map_err(|_| {
            text::TextError::local("HOST_UNAVAILABLE", "Masaüstü bağlantısı kullanılamıyor.")
        })?
}

#[tauri::command]
async fn submit_windows_command(
    state: tauri::State<'_, Arc<Supervisor>>,
    task_id: String,
    action_id: String,
    text: String,
) -> Result<tasks::TaskView, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        supervisor.submit_windows_command(&task_id, &action_id, &text)
    })
    .await
    .map_err(|_| {
        text::TextError::local("HOST_UNAVAILABLE", "Masaüstü bağlantısı kullanılamıyor.")
    })?
}

#[tauri::command]
async fn list_windows_tasks(
    state: tauri::State<'_, Arc<Supervisor>>,
) -> Result<tasks::TaskList, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || supervisor.list_windows_tasks())
        .await
        .map_err(|_| {
            text::TextError::local("HOST_UNAVAILABLE", "Masaüstü bağlantısı kullanılamıyor.")
        })?
}

#[tauri::command]
async fn decide_windows_approval(
    state: tauri::State<'_, Arc<Supervisor>>,
    task_id: String,
    approval_id: String,
    approve: bool,
) -> Result<tasks::TaskView, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || {
        supervisor.windows_operation(&task_id, Some((&approval_id, approve)), false)
    })
    .await
    .map_err(|_| {
        text::TextError::local("HOST_UNAVAILABLE", "Masaüstü bağlantısı kullanılamıyor.")
    })?
}

#[tauri::command]
async fn cancel_windows_task(
    state: tauri::State<'_, Arc<Supervisor>>,
    task_id: String,
) -> Result<tasks::TaskView, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || supervisor.windows_operation(&task_id, None, true))
        .await
        .map_err(|_| {
            text::TextError::local("HOST_UNAVAILABLE", "Masaüstü bağlantısı kullanılamıyor.")
        })?
}

#[tauri::command]
async fn cloud_settings(
    state: tauri::State<'_, Arc<Supervisor>>,
) -> Result<chat::CloudState, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || supervisor.cloud_settings())
        .await
        .map_err(|_| text::TextError::contract())?
}
#[tauri::command]
async fn configure_cloud(
    state: tauri::State<'_, Arc<Supervisor>>,
    config: chat::CloudConfig,
) -> Result<chat::CloudState, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || supervisor.configure_cloud(config))
        .await
        .map_err(|_| text::TextError::contract())?
}
#[tauri::command]
async fn start_chat(
    state: tauri::State<'_, Arc<Supervisor>>,
    request_id: String,
    text: String,
) -> Result<chat::ChatReply, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || supervisor.start_chat(&request_id, &text))
        .await
        .map_err(|_| text::TextError::contract())?
}
#[tauri::command]
async fn poll_chat(
    state: tauri::State<'_, Arc<Supervisor>>,
    request_id: String,
) -> Result<chat::ChatReply, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || supervisor.poll_chat(&request_id, false))
        .await
        .map_err(|_| text::TextError::contract())?
}
#[tauri::command]
async fn cancel_chat(
    state: tauri::State<'_, Arc<Supervisor>>,
    request_id: String,
) -> Result<chat::ChatReply, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || supervisor.poll_chat(&request_id, true))
        .await
        .map_err(|_| text::TextError::contract())?
}
#[tauri::command]
async fn clear_chat(state: tauri::State<'_, Arc<Supervisor>>) -> Result<bool, text::TextError> {
    let supervisor = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || supervisor.clear_chat())
        .await
        .map_err(|_| text::TextError::contract())?
}

fn main() {
    let supervisor = Arc::new(Supervisor::new());
    let startup = supervisor.clone();
    let app = tauri::Builder::default()
        .manage(supervisor)
        .invoke_handler(tauri::generate_handler![
            backend_status,
            backend_restart,
            process_text,
            create_simulated_task,
            list_simulated_tasks,
            get_simulated_task,
            decide_simulated_approval,
            cancel_simulated_task,
            reconcile_simulated_task,
            create_windows_task,
            submit_windows_command,
            list_windows_tasks,
            decide_windows_approval,
            cancel_windows_task,
            cloud_settings,
            configure_cloud,
            start_chat,
            poll_chat,
            cancel_chat,
            clear_chat
        ])
        .setup(move |_| {
            tauri::async_runtime::spawn_blocking(move || {
                startup.start(false);
            });
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("NOVA masaüstü başlatılamadı");
    app.run(|handle, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            handle.state::<Arc<Supervisor>>().stop();
        }
    });
}
