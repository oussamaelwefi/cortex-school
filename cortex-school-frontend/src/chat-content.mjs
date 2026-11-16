const content = {
  guardian: {
    subtitle: "A little support for your child’s learning journey.",
    welcome:
      "Hello! 👋 I’m your Cortex family assistant.\nI can help you support learning at home or find the right words for your child’s teacher.",
    suggestions: [
      "Help me write a message to my child’s teacher",
      "Suggest a learning activity to do at home",
      "Help me build a homework routine for my child",
    ],
    context:
      "The user is a parent or guardian. Tailor your response to supporting their child, learning at home, and communicating with teachers.",
  },
  teacher: {
    subtitle: "A little inspiration for your school day.",
    welcome:
      "Hello! 👋 I’m your Cortex teaching assistant.\nI can help with classroom ideas, lesson planning, and messages to families.",
    suggestions: [
      "Help me write a message to a parent",
      "Suggest a classroom activity",
      "Help me plan my school day",
    ],
    context:
      "The user is a teacher. Tailor your response to teaching, classroom planning, and communication with families.",
  },
  admin: {
    subtitle: "A little support for your school community.",
    welcome:
      "Hello! 👋 I’m your Cortex school assistant.\nI can help with school communication, welcoming families, and organizing your day.",
    suggestions: [
      "Help me draft an announcement for families",
      "Create a checklist for welcoming a new student",
      "Help me organize school administration tasks",
    ],
    context:
      "The user is a school administrator. Tailor your response to school operations and communication with the school community.",
  },
};
export function getChatContent(role) {
  return content[role] || content.guardian;
}
