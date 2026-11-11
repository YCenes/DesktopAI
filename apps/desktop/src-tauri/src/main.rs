#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod backend;
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
            reconcile_simulated_task
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
