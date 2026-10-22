# Exception Management Policy

Document owner: Supply Planning. Applies to all planning exceptions generated for Northwind Industrial Systems (a fictional company used for this portfolio project).

## Purpose

Exceptions are the plan telling the planner where to look. This policy defines the exception types and how planners work through them.

## Exception types

- SHORTAGE: projected available quantity is below zero. Handled under the Shortage Escalation Policy.
- NO_SUPPLY: there is demand but no planned supply in the week. Always HIGH severity.
- BELOW_SAFETY_STOCK: projected available quantity is above zero but below the safety stock quantity. Handled under the Safety Stock Policy.
- EXCESS: projected available quantity is far above safety stock. Handled under the Excess Inventory Policy.

## Severity

Severity is HIGH, MEDIUM or LOW. A BELOW_SAFETY_STOCK exception is MEDIUM when projected available is less than half of safety stock and LOW otherwise. EXCESS exceptions are LOW unless Finance has flagged the value.

## Working order

Planners work exceptions in this order: HIGH severity first, then by ABC class with Class A before B before C, then by the soonest week. This ordering is applied inside the weekly cycle described in the Planning Cadence Policy.

## Notes and ownership

Every exception reviewed must carry a short note stating the decision. Exceptions belong to the planner code recorded on the item. When a planner is absent, their exceptions are covered by the other planners on the same team.

## Repeat exceptions

When the same item and location has had BELOW_SAFETY_STOCK exceptions in three or more consecutive weeks, the planner must record a root cause, such as wrong safety stock, unreliable supplier or forecast bias, rather than closing each week separately.

## Closure

An exception is closed when its condition no longer holds in the latest plan, or when the planner records an approved decision to accept it.
