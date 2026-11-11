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
#[serde(tag = "tool_id", deny_unknown_fields)]
pub enum ActionRequest {
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
    pub fn task_id(&self) -> &str {
        match self {
            Self::Open { task_id, .. } | Self::Search { task_id, .. } => task_id,
        }
    }
    pub fn validate(&self) -> Result<(), TextError> {
        let (task, action, valid) = match self {
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
            || !self.simulated
            || self.external_calls != 0
            || self.events.is_empty()
            || self.events.len() > 64
            || self.events.iter().enumerate().any(|(i, e)| {
                e.sequence as usize != i + 1 || e.kind.len() > 64 || !e.created_at.is_finite()
            })
            || self.error_code.as_ref().is_some_and(|v| v.len() > 64)
            || self.result.as_ref().is_some_and(|r| {
                !r.simulated
                    || r.message.chars().count() > 512
                    || r.status != self.status
                    || !matches!(r.status, TaskStatus::Succeeded | TaskStatus::Failed)
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
        for tool in ["windows.open_app", "shell", "fake.unknown"] {
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
}
