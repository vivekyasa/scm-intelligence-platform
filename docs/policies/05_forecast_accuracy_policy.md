# Forecast Accuracy Policy

Document owner: Demand Planning. Applies to all forecasted items of Northwind Industrial Systems (a fictional company used for this portfolio project).

## Purpose

The supply plan is only as good as the demand forecast behind it. This policy defines how forecast accuracy is measured and what happens when it is poor.

## Measurement

Forecast accuracy is measured with MAPE, the mean absolute percentage error, calculated as the average of the absolute difference between actual and forecast demand divided by actual demand. Weeks where actual demand was zero are excluded. MAPE is calculated per item and location over a rolling 13 week window.

## Targets by class

- Class A items: MAPE of 20 percent or lower
- Class B items: MAPE of 30 percent or lower
- Class C items: MAPE of 40 percent or lower

Forecast error naturally grows with the forecast horizon, so accuracy targets apply to forecasts made 4 weeks ahead.

## Bias

Bias is the signed average error. A forecast that is consistently too high or too low is more damaging than one that is noisy but centered. An item whose bias exceeds plus or minus 10 percent for 8 consecutive weeks is flagged as biased and must be reviewed by the demand planner.

## Review process

Items that miss their MAPE target for two consecutive months go on the Forecast Review List. The demand planner investigates and records one of: a one-off event, a change in demand pattern, a data problem, or a model problem. Items on the list for three consecutive months are escalated to the Demand Planning Manager.

## Impact on safety stock

Persistent forecast error is a legitimate reason to request an off-cycle safety stock review under the Safety Stock Policy.
