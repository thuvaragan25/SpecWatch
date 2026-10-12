# Invoice Service PRD

This document describes the requirements for the invoice service.

## Invoice Sending

### Invoice Approval

All external invoices must be explicitly approved by the operator before they are sent.

### Password Reset Tokens

Password reset tokens shall expire after 30 minutes.

## Architecture

### Layering

API routes must not directly access repositories; they may only call services.

## Non-Goals

This service does not handle recurring subscription billing.

## Examples

For example, a draft invoice created on Monday and approved on Tuesday is sent on Tuesday.

## Background

This section is here for context only and imposes no behavioral constraint.
