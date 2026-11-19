const content = {
  guardian: {
    subtitle: "Your children’s school information, with helpful answers.",
    welcome:
      "Hello! 👋 I’m your Cortex family assistant.\nI can look up your children’s attendance, school messages and policies, or help you write to a teacher.",
    suggestions: [
      "Help me write a message to my child’s teacher",
      "Show my children’s recent attendance",
      "Which school messages still need my acknowledgement?",
    ],
    context:
      "The user is a parent or guardian. Tailor your response to supporting their child, learning at home, and communicating with teachers.",
  },
  teacher: {
    subtitle: "Your classes, attendance and family communication.",
    welcome:
      "Hello! 👋 I’m your Cortex teaching assistant.\nI can look up your assigned classes, attendance and family acknowledgements, or help draft messages.",
    suggestions: [
      "Help me write a message to a parent",
      "Who is absent from my classes today?",
      "Which families have not acknowledged my updates?",
    ],
    context:
      "The user is a teacher. Tailor your response to teaching, classroom planning, and communication with families.",
  },
  admin: {
    subtitle: "Ask about your school’s records and policies.",
    welcome:
      "Hello! 👋 I’m your Cortex school assistant.\nI can look up students, classes, registrations, invitations and school policies, or help draft an announcement.",
    suggestions: [
      "Help me draft an announcement for families",
      "How many students are enrolled in the school?",
      "Which acknowledgements are overdue?",
    ],
    context:
      "The user is a school administrator. Tailor your response to school operations and communication with the school community.",
  },
};
export function getChatContent(role) {
  return content[role] || content.guardian;
}
