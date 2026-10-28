import React from "react";
import codex from "./agent-icons/codex.svg";
import opencode from "./agent-icons/opencode.svg";
import deepseek from "./agent-icons/deepseek.svg";
import claude from "./agent-icons/claude.svg";
import pi from "./agent-icons/pi.svg";

const logos = { codex, opencode, dsh: deepseek, claude, pi };

export function AgentLogo({ id, size = 18 }) {
  return <img className="agent-logo" src={logos[id]} alt="" aria-hidden="true"
    width={size} height={size} draggable={false} />;
}
