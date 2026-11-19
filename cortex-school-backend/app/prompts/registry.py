"""File-based prompt registry. Add entries here when you create new workflows."""

PROMPTS = {
    "workflow_simple_reply": {
        "template": "chat/workflow_simple_reply",
        "description": "Role-scoped school assistant with read-only data and policy tools",
        "version": "school_data_chat_v1",
    },
    "workflow_teacher_update_draft": {
        "template": "teacher/update_draft",
        "description": "Bounded teacher update draft from teacher observations",
        "version": "teacher_update_draft_v2",
    },
    "workflow_guardian_weekly_explanation": {
        "template": "guardian/weekly_explanation",
        "description": "Grounded guardian explanation from authorized weekly sources",
        "version": "guardian_weekly_explanation_v1",
    },
}
