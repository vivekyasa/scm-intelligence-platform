# Excess Inventory Policy

Document owner: Supply Planning and Finance. Applies to all stocked items of Northwind Industrial Systems (a fictional company used for this portfolio project).

## Purpose

Excess inventory ties up cash and warehouse space and can become obsolete. This policy defines when stock is considered excess and what planners should do about it.

## Definition of excess

Projected available quantity is excess when it is more than 6 times the item's safety stock quantity and the surplus above that threshold is at least 50 units. Both conditions must be true, which avoids flagging low volume items for trivial amounts.

An EXCESS exception is generated for each future week where the condition holds.

## Priority

Excess on Class A items has the highest priority because unit costs are highest. Excess on Class C items is reviewed monthly in bulk rather than item by item.

## Actions, in order of preference

1. Cancel or push out open purchase orders and planned orders that are driving the excess.
2. Transfer surplus stock to a location that is short or below safety stock.
3. Stop replenishment for the item until projected available returns to within 4 times safety stock.
4. Raise the item with Sales for promotion or bundling.
5. Request an obsolescence review from Finance when the excess is expected to last longer than 26 weeks.

## Reporting

Finance receives a monthly excess inventory report by value. Any single item with excess value above 25,000 dollars must be reviewed with the Supply Planning Manager in the next weekly planning meeting.
