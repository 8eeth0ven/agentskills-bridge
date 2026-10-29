---
name: order-quote
description: Calculate a deterministic order quote with validation, discount and shipping.
---

# Order quote
The workflow accepts request with items and optional vip=false.
items must be a nonempty list of objects; quantity must be a positive integer and unit_cents a nonnegative integer. Boolean values are not integers for this rule.
If items are invalid, return exactly {"status":"rejected","reason":"invalid_items"} and perform no calculation.
Otherwise subtotal_cents is the sum of quantity * unit_cents.
discount_cents equals subtotal_cents // 10 when vip is true, otherwise zero.
net_cents = subtotal_cents - discount_cents.
shipping_cents is zero if net_cents >= 10000, otherwise 500.
Return exactly {"status":"ok","subtotal_cents":subtotal_cents,"discount_cents":discount_cents,"shipping_cents":shipping_cents,"total_cents":net_cents+shipping_cents}.
Use real executable tools for validation and quoting; the workflow must validate before pricing and take the rejected branch without calling pricing.
Do not access network services or charge any money.
