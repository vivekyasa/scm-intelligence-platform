# Week 1 SQL Exercises

Twenty queries, roughly in order of difficulty. **Write these yourself.** This is the
part of the project that closes your actual gap, and it is the part an interviewer can
test live on a screen share.

Rules I would hold yourself to:

- Write the query before looking anything up. Get it wrong first, then fix it.
- When you get stuck on syntax, look up the syntax, not the answer.
- Save each one as `sql/answers/qNN.sql` so you build a reference you wrote.
- For 13 onward, if you cannot get there in 30 minutes, ask me and I will explain the
  concept rather than hand you the query.

Numbers 13 to 20 are the ones that matter. Everything before them is warm-up.

---

## Warm-up: filtering, joining, grouping

**1.** List every A-class item with a lead time over 28 days, longest lead time first.

**2.** Count items by product family and ABC class, as a two-column breakdown.

**3.** Total forecast quantity by region for the next 8 weeks.
*You will need to join through `locations`, and filter on `week_start`.*

**4.** Which five items have the highest total forecast value (quantity times unit cost)
over the full horizon?

**5.** List all HIGH severity exceptions in the next 4 weeks with the item number,
location code and message.

**6.** How many distinct items are stocked at each location?

---

## Intermediate: aggregation and date logic

**7.** For each exception type, show the count and the total quantity impact, sorted by
count descending.

**8.** Find items that have a shortage exception at more than one location.

**9.** For each planner code, how many HIGH severity exceptions do they own in the next
6 weeks? This is the "who is having a bad week" query.

**10.** Show total forecast quantity by month rather than week.
*`date_trunc` is what you want.*

**11.** List items where safety stock is more than 3 times the average weekly forecast.
These are potentially over-stocked policies.

**12.** Which items appear in `items` but have no rows at all in `supply_plan`?
*Two ways to write this. Try both, then compare with `EXPLAIN`.*

---

## The ones that count: window functions and real analysis

**13. Forecast error.** For every item and location in the history period, calculate
MAPE: the mean of `|actual - forecast| / actual` as a percentage. Exclude weeks where
actual demand was zero. Return the worst 20 items by MAPE.

**14. Weeks of cover.** For each item and location in the current week, calculate how
many weeks of forward demand the projected available quantity covers. Use the average
forecast over the next 8 weeks as the weekly demand rate.

**15. First shortage week.** For each item and location that goes negative at any point,
find the first week it does. Return item number, location, that week, and how many weeks
away it is.
*A window function with `ROW_NUMBER()` partitioned by item and location.*

**16. Running inventory.** For one item at one location, show week by week: opening
stock, receipts, demand, and a running cumulative total of demand across the horizon.
*`SUM() OVER (ORDER BY week_start)`.*

**17. Week over week change.** For each item, show the week over week percentage change
in forecast quantity, and flag any week where it moved more than 40%.
*`LAG()`.*

**18. Rank within group.** Within each product family, rank items by total forecast
value and return only the top 3 per family.
*`RANK()` or `DENSE_RANK()` inside a subquery or CTE. Know why you picked one.*

**19. Exception streaks.** Find items that have a `BELOW_SAFETY_STOCK` exception in 3 or
more consecutive weeks at the same location. This is a genuinely hard one, and it is the
kind of question a planner actually asks.
*The usual trick is a gaps-and-islands approach: `week_start` minus a row number gives
a constant value for consecutive runs.*

**20. Reconstruct the exceptions.** Write a query against `inventory_position` and
`items` that reproduces the `SHORTAGE` and `BELOW_SAFETY_STOCK` rows in
`plan_exceptions`. Compare your result to the table and account for any difference.

Number 20 is the most useful one in the whole list. The exceptions were derived from the
position data by the generator, so a correct query should reproduce them exactly. If
yours does not match, either your query is wrong or you have found a real discrepancy,
and figuring out which is the actual skill. It also becomes an eval case in week 4.

---

## When you are done

You should be able to answer, without looking anything up:

- When do you need `GROUP BY` versus a window function?
- What is the difference between `RANK`, `DENSE_RANK` and `ROW_NUMBER`?
- Why does a `LEFT JOIN` with a `WHERE` clause on the right table behave like an
  `INNER JOIN`, and how do you avoid that?
- What does a CTE cost you versus a subquery in Postgres?

If any of those are shaky after twenty queries, tell me and we will drill that one.
