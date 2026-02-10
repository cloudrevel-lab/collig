# Product Requirements Document (PRD) - Collig

## 1. Product Overview
**Collig** is an AI-powered co-worker/personal assistant with OS-level permissions. It is designed to automate tasks, interact with the operating system, and provide an extensible platform for developers to contribute skills. Users can also trade skills in a marketplace.

## 2. User Roles
- **User**: Interacts with the AI, manages skills, and uses the marketplace.
- **Developer**: Creates and publishes skills to the marketplace.
- **Admin**: Manages the platform, reviews skills, and handles disputes.

## 3. Core Features
### 3.1. AI Assistant
- **Chat Interface**: Natural language interaction with the AI.
- **Context Awareness**: Understands the user's OS context (open windows, files, etc.).
- **Task Execution**: Executes OS-level commands (file management, app launching, etc.).

### 3.2. Skill System
- **Skill Structure**: Modular capabilities (e.g., "Send Email", "Organize Files").
- **Extensibility**: Python-based skill modules.
- **Permission Management**: Granular permissions for each skill.

### 3.3. Skill Marketplace
- **Browse & Search**: Find skills by category, rating, or price.
- **Buy & Sell**: Transaction system for premium skills.
- **Reviews & Ratings**: User feedback on skills.

## 4. UI/UX Requirements
- **Frontend**: Built with **Vue.js + Vite**.
- **Design**: Clean, modern, and responsive interface.
- **Dark Mode**: Support for system-preferred theme.

## 5. Security
- **OS Permissions**: Strict sandboxing and user approval for sensitive actions.
- **API Keys**: Secure storage using `.env` files.
- **Skill Verification**: Automated and manual review of submitted skills.
