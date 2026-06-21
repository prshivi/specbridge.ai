# 1 Account Registration

The registration capability creates a new customer account.

## 1.1 Functional Requirements

REQ-001: The platform must validate the email address before creating an account.

## 1.2 Business Rules

BR-001: A verified email address may belong to only one active account.

## 1.3 Acceptance Criteria

Given a new customer, when they submit a valid registration form, then the account is created.

## 1.4 Workflow

1. The customer enters account details.
2. The platform validates the email address.
3. The platform creates the account.

## 1.5 Validation Matrix

| Field | Rule |
| --- | --- |
| Email | Required and unique |
| Password | At least 12 characters |

