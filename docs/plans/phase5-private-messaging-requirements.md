We are continuing the Société mobile/backend project.

Repository:
 /Users/shashankpapani/Coding/Projects/Societe

Before making changes, read:
- @docs/societe_cursor_master_architecture.md
- @docs/plans/phase4-calling-cards-realtime.md
- @.cursor/rules/societe.mdc
- all relevant ADRs
- the Calling Card implementation
- the connection_grants model
- the realtime publisher
- the outbox dispatcher
- the mobile offline queue
- git status
- git log --oneline -5

CURRENT VERIFIED STATE

- Phase 0 foundation complete
- Phase 1 identity and venue discovery complete
- Phase 2 presence and geofencing complete
- Phase 3 Live Vibes complete
- Real iOS gallery image upload reaches published and appears in the Echo Basement feed
- Phase 4 Calling Cards and realtime complete
- Two separate development users were verified simultaneously at Echo Basement
- Same-venue discovery works
- Calling Card send, receive, and accept work
- An accepted Calling Card creates a connection_grant
- Local development feature flags required:
  FF_CALLING_CARDS=true
  FF_VENUE_PEOPLE_DISCOVERY=true
  FF_LOCATION_SIMULATOR=true
- Do not modify, expose, or commit local .env files
- Do not regress:
  - iOS simulator support
  - expo-image-picker
  - expo-file-system uploads
  - Live Vibes media processing
  - presence simulation
  - verified presence
  - venue discovery
  - Calling Cards
  - connection grants
  - realtime outbox behavior
  - local development authentication

PHASE 5: PRIVATE MESSAGING

Implement private one-to-one messaging built on accepted connection_grants.

First inspect the repository and produce a detailed implementation plan only.

Do not edit code until I explicitly approve the plan.
Do not commit, tag, push, deploy, or apply Terraform.

CORE RULE

Only users with a valid, active, non-revoked connection_grant may message each other.

REST remains authoritative.

Realtime events only notify clients that authoritative state has changed. Clients must fetch authoritative REST state after receiving an event.

BACKEND

Add an Alembic migration after migration 0005.

Create the following data model.

1. conversations

Required fields:
- id
- user_low_id
- user_high_id
- originating_connection_grant_id
- created_at
- updated_at
- last_message_at
- revoked_at
- revoked_reason where appropriate

Rules:
- user_low_id and user_high_id must represent a canonical ordered user pair
- enforce a unique canonical user pair
- reject self-conversations
- retain conversations after users leave the venue
- conversation creation must be idempotent
- conversation creation must return the existing conversation for the same pair

Do not place a global archived timestamp directly on the conversation if archiving is user-specific. Store user-specific archive state in conversation membership/read-state records.

2. messages

Required fields:
- id
- conversation_id
- sender_user_id
- client_message_id
- body
- status
- created_at
- edited_at
- deleted_at
- moderation metadata where appropriate

Rules:
- unique(sender_user_id, client_message_id)
- validate that sender belongs to the conversation
- enforce configured body length limits
- do not allow an empty or whitespace-only message
- do not implement editing in the API during this phase even if edited_at is reserved
- do not hard-delete message history by default
- retries with the same client_message_id must return the same message
- message and outbox event must commit atomically

3. conversation_members

Use a membership/read-state table with one row per user per conversation.

Fields:
- conversation_id
- user_id
- last_read_message_id
- last_read_at
- unread_count or enough authoritative state to calculate it efficiently
- muted_at
- archived_at
- created_at
- updated_at

Rules:
- exactly two members per one-to-one conversation
- archived and muted state are per member
- opening a conversation must mark eligible messages as read
- one user archiving a conversation must not archive it for the other user

AUTHORIZATION

Before every messaging action verify:

- authenticated user exists
- account status is active
- user is a conversation participant
- an active connection_grant exists for the two participants
- the grant has not expired, been revoked, or been superseded
- neither user has blocked the other
- message body is within configured limits
- message rate limits pass
- abuse/risk policy checks pass where existing infrastructure supports them

Important behavior:

- Leaving the venue must not delete an accepted connection or conversation
- Leaving the venue must not prevent messaging after an accepted Calling Card
- Blocking must immediately prevent new messages
- Revoking the connection_grant must immediately prevent new messages
- Historical messages may remain readable according to product policy, but no new message may be sent after blocking or revocation
- Do not expose private profile information beyond the scopes already granted by connection_grants
- Do not require a current venue lease for messaging after the connection has been accepted

API

Implement versioned endpoints:

POST /v1/conversations
GET /v1/conversations
GET /v1/conversations/{conversation_id}
GET /v1/conversations/{conversation_id}/messages
POST /v1/conversations/{conversation_id}/messages
POST /v1/conversations/{conversation_id}/read
POST /v1/conversations/{conversation_id}/archive

Consider adding:

POST /v1/conversations/{conversation_id}/unarchive

only if it fits the existing API conventions cleanly.

Endpoint behavior:

POST /v1/conversations
- accepts the other user ID or connection_grant ID
- verifies the active grant
- creates or returns the existing canonical conversation
- must be idempotent

GET /v1/conversations
- returns only conversations for the authenticated user
- supports signed cursor pagination
- includes minimal participant display data allowed by grant scopes
- includes last message preview
- includes last message timestamp
- includes unread count
- excludes archived conversations unless explicitly requested

GET /v1/conversations/{id}/messages
- supports signed cursor pagination
- use stable deterministic ordering
- support fetching older messages
- do not expose deleted message bodies
- never return another conversation’s messages

POST /v1/conversations/{id}/messages
- accepts body and stable client_message_id
- also support Idempotency-Key where consistent with the existing architecture
- repeated retries must create exactly one message
- return the authoritative server message
- do not report “sent” before the database transaction commits

POST /v1/conversations/{id}/read
- advances read state monotonically
- must not move last-read state backward
- updates unread count consistently
- emits a minimal message.read event

POST /v1/conversations/{id}/archive
- archives only for the authenticated member
- must not affect the other member

Use the project’s existing signed cursor implementation.

REALTIME AND OUTBOX

Add outbox event types:

- conversation.created
- conversation.archived
- conversation.revoked
- message.created
- message.read

Persist business changes and outbox rows atomically.

Use the existing:
- Outbox model
- outbox dispatcher
- RealtimePublisher abstraction
- local realtime provider
- push fallback mechanism

Realtime payloads must be minimal.

Preferred payload examples:

message.created:
- event_id
- conversation_id
- message_id
- sender_user_id
- created_at
- optional short sanitized preview

message.read:
- event_id
- conversation_id
- reader_user_id
- last_read_message_id
- read_at

Do not include full private conversation history in realtime or push payloads.

Clients receiving realtime events must invalidate or refetch REST queries.

Add deduplication using event_id.

Push fallback:
- only use minimal notification text
- do not expose sensitive message contents by default
- respect notification preferences when available
- local stub only in this phase unless production push is already configured

MOBILE

Add a clear Messages entry inside Connect or add a Messages tab if the current navigation structure supports it without broad refactoring.

Build:

1. Conversation list
- participant label/avatar placeholder
- last message preview
- last message timestamp
- unread badge
- empty state
- loading state
- archived filtering
- pull-to-refresh or equivalent refresh behavior
- realtime invalidation

2. Conversation screen
- paginated message history
- current user and other user message alignment
- message timestamps
- pending/sending state
- sent state
- failed retryable state
- failed permanent state
- retry button
- scroll behavior
- load older messages
- mark-as-read when opened and when new visible messages arrive

3. Message composer
- text-only
- trim and validate body
- enforce length limit
- stable client_message_id generated before enqueue
- prevent accidental duplicate sends
- display clear errors
- disable send for empty messages

4. Offline SQLite queue
- reuse or extend the existing Phase 4 offline queue architecture
- persist queued messages
- stable client_message_id
- retry after reconnect
- exponential backoff where appropriate
- distinguish retryable and permanent failures
- never create duplicate messages
- never display a message as successfully sent before server confirmation

Suggested queue states:
- queued
- sending
- server_confirmed
- failed_retryable
- failed_permanent

5. Realtime
- listen for message.created
- listen for message.read
- deduplicate by event_id
- invalidate conversation and message queries
- update unread indicators
- maintain REST as the source of truth
- handle websocket reconnects without duplicating messages

Do not implement:
- images
- videos
- voice messages
- GIFs
- typing indicators
- online presence
- reactions
- message editing
- disappearing messages
- message forwarding
- group chats
- end-to-end encryption
- link previews

TESTS

Add backend tests for:

- only users with an active connection_grant can create a conversation
- duplicate conversation creation returns the same conversation
- canonical pair uniqueness
- self-conversation rejection
- non-connected users cannot create conversations
- non-participants cannot read a conversation
- non-participants cannot read messages
- non-participants cannot send
- blocked users cannot send
- revoked grants prevent new messages
- expired grants prevent new messages where applicable
- leaving a venue does not prevent messaging after acceptance
- message body validation
- whitespace-only message rejection
- message rate limits
- idempotent message retries create exactly one message
- signed cursor pagination
- deterministic message ordering
- conversation pagination
- unread-count correctness
- read state moves forward only
- archive is per user
- message and outbox atomicity
- realtime event deduplication
- push fallback
- existing Phase 0 through Phase 4 tests remain green

Add mobile tests for:

- conversation list rendering
- unread indicators
- message composer validation
- optimistic queued state
- successful server confirmation
- retryable failure
- permanent failure
- offline queue persistence
- reconnect retry
- duplicate client_message_id protection
- realtime query invalidation
- marking a conversation as read

MIGRATION AND DATA INTEGRITY

The migration must:

- upgrade cleanly from the Phase 4 schema
- work against an empty database
- include foreign keys
- include check constraints
- include canonical pair uniqueness
- include useful conversation and message indexes
- include unread/read-state indexes where needed
- preserve all existing Phase 0 through Phase 4 data

Suggested indexes:
- conversations(user_low_id, user_high_id)
- conversations(last_message_at)
- conversation_members(user_id, archived_at)
- messages(conversation_id, created_at, id)
- messages(sender_user_id, client_message_id)

DOCUMENTATION

Create:

docs/plans/phase5-private-messaging.md

Add ADRs where architectural decisions are not already covered, especially for:

- canonical one-to-one conversation identity
- message idempotency
- offline queue semantics
- read-state and unread-count strategy
- REST-authoritative realtime behavior

Update:

docs/current-state.md

Include:
- completed Phase 5 scope
- latest migration
- feature flags
- manual tests
- known limitations
- next recommended phase

MANUAL ACCEPTANCE

Use Dev Alpha and Dev Beta or the existing two local development users.

1. Accept a Calling Card.
2. Open or create the resulting conversation.
3. Alpha sends a message.
4. Beta receives it without manually refreshing.
5. Beta replies.
6. Alpha receives the reply without manually refreshing.
7. Unread count appears when a conversation has unread messages.
8. Unread count clears when the conversation opens.
9. Disable network.
10. Send one message while offline.
11. Reconnect.
12. Verify exactly one copy appears.
13. Leave Echo Basement.
14. Confirm messaging still works because the connection was previously accepted.
15. Block one user.
16. Confirm new messages are rejected immediately.
17. Confirm no duplicate messages appear after reconnecting or refreshing.

QUALITY GATES

Run and report:

- backend formatting
- backend lint
- mypy
- Alembic migration from current schema
- Alembic migration from empty database
- complete pytest suite
- OpenAPI generation/check
- mobile typecheck
- mobile lint
- mobile tests
- Docker Compose build
- Terraform fmt and validate only if Terraform files change
- secret scan
- git diff --check

Do not run production deployments.
Do not apply Terraform.
Do not commit.
Do not tag.
Do not push.

PLAN OUTPUT REQUIRED BEFORE EDITING

Before changing code, provide:

1. Current repository findings
2. Exact files/modules expected to change
3. Proposed migration design
4. Proposed API contracts
5. Authorization flow
6. Idempotency strategy
7. Realtime and outbox flow
8. Mobile architecture
9. Offline queue strategy
10. Test plan
11. Risks and assumptions
12. Explicit confirmation that no code has been edited yet

Stop after presenting the plan and wait for approval.