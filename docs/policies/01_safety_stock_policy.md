# Safety Stock Policy

Document owner: Supply Planning. Applies to all stocked items at every plant, distribution center and forward stock location of Northwind Industrial Systems (a fictional company used for this portfolio project).

## Purpose

Safety stock protects customer service against demand variability and supply delays. It is not a target for normal operations. It is a buffer that planners should rarely need to touch.

## Coverage targets by ABC class

Safety stock is set as weeks of forward demand cover, based on the item's ABC class:

- Class A items: 2.5 weeks of cover
- Class B items: 2.0 weeks of cover
- Class C items: 1.5 weeks of cover

Weeks of cover is calculated against the average weekly forecast over the next 8 weeks. The resulting quantity is stored on the item record as the safety stock quantity.

## What counts as a breach

A projected available quantity below the safety stock quantity in any future week is a safety stock breach and generates a BELOW_SAFETY_STOCK exception. A projected available quantity below zero is a shortage and is handled under the Shortage Escalation Policy instead.

A breach in a single week that recovers the following week is low priority. A breach that persists for three or more consecutive weeks at the same location must be reviewed, because it usually means the safety stock level or the supply plan is wrong rather than demand being unusual.

## Review cadence

Safety stock levels are reviewed quarterly for Class A items and twice a year for Class B and C items. Planners may request an off-cycle review when forecast error for an item has exceeded its target for two consecutive months.

## Who can change safety stock

Planners can adjust safety stock within plus or minus 20 percent of the policy level. Changes beyond that range need approval from the Supply Planning Manager and must be documented with a reason.
