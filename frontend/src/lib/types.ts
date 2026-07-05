export interface Topic {
  id: string;
  name: string;
  description: string;
  created_at: string;
}

export interface Card {
  id: string;
  topic_id: string;
  title: string;
  body: string;
  kind: string; // fact | concept | mechanism | question
  confidence: string; // verified | heard | unsure
  source_url: string;
  due: string;
  created_at: string;
  due_now?: boolean;
  stability?: number;
}

export interface Link {
  id: string;
  from_id: string;
  to_id: string;
  kind: string; // builds_on | example_of | contradicts | related
  reason: string;
}

export interface GraphData {
  topics: Topic[];
  cards: Card[];
  links: Link[];
}

export interface ProposalLink {
  to_title: string;
  kind: string;
  reason: string;
}

export interface Proposal {
  title: string;
  body: string;
  kind: string;
  topic: string;
  confidence: string;
  source_url: string;
  links: ProposalLink[];
}

export interface QuizPayload {
  card_id: string;
  card_title: string;
  question: string;
}

export interface Note {
  id: string;
  card_id: string | null;
  topic_id: string | null;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface Review {
  id: string;
  card_id: string;
  question: string;
  user_answer: string;
  grade: string;
  feedback: string;
  mode: string;
  created_at: string;
}

export interface ChatMsg {
  role: "user" | "assistant";
  content: string;
}
