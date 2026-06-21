# Customer Support Case Management Platform

## 1. Document Overview

### 1.1 Purpose

This Business Requirements Document defines a customer support case management
platform for receiving, assigning, tracking, resolving, and reporting customer
support requests.

### 1.2 Business Objectives

- Reduce the average time required to assign a new support case.
- Give support agents one place to review customer requests and case history.
- Give support managers visibility into overdue and high-priority cases.
- Notify customers when important case status changes occur.
- Preserve an auditable history of case activity.

### 1.3 Stakeholders

- Customer Support Manager
- Support Agent
- Customer
- System Administrator
- Reporting Analyst

## 2. Scope

### 2.1 In Scope

- Customer case submission
- Case assignment
- Priority and status management
- Internal comments
- Customer notifications
- Search and filtering
- Operational reporting
- Audit history
- Customer profile integration

### 2.2 Out of Scope

- Voice-call recording
- Workforce scheduling
- Customer billing
- Knowledge-base authoring

## 3. Actors and Permissions

### 3.1 Customer

A customer can create a support case and view cases associated with their
customer profile.

### 3.2 Support Agent

A support agent can view assigned cases, add internal comments, update case
status, and request additional information from the customer.

### 3.3 Support Manager

A support manager can view all cases, change case priority, reassign cases, and
access operational reports.

### 3.4 System Administrator

A system administrator can configure case categories and deactivate support
agent accounts.

## 4. Functional Requirements

### 4.1 Case Submission

REQ-001: The platform shall allow a customer to submit a support case with a
subject, description, category, and contact email address.

REQ-002: The platform shall generate a unique case reference after successful
submission.

REQ-003: The platform shall reject a case when the subject, description,
category, or contact email address is missing.

REQ-004: The contact email address shall use a valid email format.

### 4.2 Case Assignment

REQ-005: A newly created case shall be placed in the unassigned queue.

REQ-006: A support manager may assign an unassigned case to an active support
agent.

REQ-007: The assigned support agent shall be notified when a case is assigned.

REQ-008: High-priority cases should be assigned quickly.

### 4.3 Case Status

REQ-009: A support agent may move an assigned case through the statuses Open,
In Progress, Waiting for Customer, Resolved, and Closed.

REQ-010: A customer shall be notified when a case moves to Waiting for Customer,
Resolved, or Closed.

REQ-011: A resolved case shall automatically close after 7 calendar days when
the customer provides no additional response.

REQ-012: Resolved cases must never close automatically.

### 4.4 Comments and History

REQ-013: Support agents may add internal comments that are not visible to the
customer.

REQ-014: The platform shall record the actor, timestamp, previous value, and new
value whenever case status, priority, or assignment changes.

REQ-015: Audit history shall be retained for at least 24 months.

### 4.5 Search and Reporting

REQ-016: Support agents shall be able to search cases by case reference,
customer email address, subject, status, priority, category, and assigned agent.

REQ-017: Support managers shall be able to view a report of new, open, overdue,
resolved, and closed cases.

REQ-018: Reports shall support filtering by date range, category, priority, and
assigned agent.

REQ-019: Reports should load quickly.

## 5. Business Rules

BR-001: Every support case must have exactly one current status.

BR-002: Only active support agents may be assigned a case.

BR-003: Only support managers may change case priority.

BR-004: A case cannot be closed while required customer information is still
outstanding.

BR-005: Internal comments must never be included in customer notifications.

BR-006: A customer may view only cases linked to their own customer profile.

## 6. Integration Requirements

### 6.1 Customer Profile Service

INT-001: The platform shall retrieve the customer name, customer identifier,
and account status from the Customer Profile Service using the submitted contact
email address.

INT-002: The support case shall still be created when the Customer Profile
Service is unavailable.

INT-003: The specification does not define how often the platform should retry
a failed Customer Profile Service request.

### 6.2 Notification Provider

INT-004: Customer and agent email notifications shall be delivered through the
Notification Provider.

INT-005: The platform shall record whether a notification request was accepted
or rejected by the Notification Provider.

## 7. Validation Rules

| Field | Validation |
| --- | --- |
| Subject | Required; maximum 150 characters |
| Description | Required; maximum 10,000 characters |
| Category | Required; must use an active configured category |
| Contact Email | Required; valid email format |
| Priority | Low, Medium, High, or Critical |
| Status | Must follow the configured case-status workflow |

## 8. Notification Rules

NOT-001: Assignment notifications shall include the case reference, subject,
priority, and a link to the case.

NOT-002: Customer notifications shall include the case reference and current
status.

NOT-003: Customer notifications shall not include internal comments.

NOT-004: Notification retry and escalation behavior is not specified.

## 9. Non-Functional Requirements

NFR-001: The platform shall maintain an audit record for privileged case
changes.

NFR-002: Customer case information shall be encrypted while transmitted between
the user interface and backend services.

NFR-003: The system shall support concurrent work by support agents.

NFR-004: The system shall be available during business operating hours.

NFR-005: Accessibility requirements have not yet been agreed.

NFR-006: Backup and recovery expectations have not yet been agreed.

## 10. Primary Workflow

### 10.1 Submit and Resolve a Case

1. The customer submits a case.
2. The platform validates the submitted fields.
3. The platform retrieves available customer profile information.
4. The platform creates the case and generates a case reference.
5. The case enters the unassigned queue.
6. A support manager assigns the case to an active support agent.
7. The agent investigates and updates the case.
8. The customer receives notifications for customer-visible status changes.
9. The agent resolves the case.
10. The case is closed according to the agreed closure rule.

## 11. Explicit Assumptions

ASM-DOC-001: Email is the only notification channel required for the first
release.

ASM-DOC-002: Case categories will be configured before production launch.

## 12. Open Questions

- What exact assignment time is expected for high-priority cases?
- Should support agents authenticate through an existing identity provider?
- What retry policy should apply to external integrations?
- What should happen after a Notification Provider rejection?
- What response-time target defines “reports should load quickly”?
- Which accessibility standard must the platform meet?
- What are the required recovery-point and recovery-time objectives?
