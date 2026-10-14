# Question
Domain: Food delivery
Order dishes from one restaurant with daily portion limits
Portions never oversold; cart holds one restaurant only

# Initial Prompt for spec/ setup

## Entities
Dish: dish_id: str, price_per_unit: int (minor units), total_portions, total_available_portions, total_reserved_portions, total_sold_portions
OrderLineItem: dish_id, units, total_price
OrderStatus: ORDER_REJECTED, ORDER_ACCEPTED, ORDER_PREPARING, ORDER_DELIVERING, ORDER_CANCELLED
Order: order_id: str, List[OrderLineItem], order_status: OrderStatus

*OrderStatus transisions*
1. ORDER_ACCEPTED -> ORDER_PREPARING -> DELIVERING
2. ORDER_REJECTED (if order cannot be fulfilled at the time of creation)
3. ORDER_ACCEPTED -> ORDER_CANCELLED (Order can be cancelled only after its accepted)
4. ORDER_PREPARING -> ORDER_CANCELLED (Order can be cancelled only after its accepted)

## APIs
1. API to list the dishes
2. API to list the card
3. API to add OrderLineItems to cart
4. API to remove OrderLineItems from cart
5. API to place the cart order -> pass an idempotency key
5.1 If request is retried with existing idempotency key also match the request hash else throw erro
6. API to list all the orders
7. API to list a particular order
8. API to create transition state

It's critical that request validations will be done at the API level
It's critical that APIs will follow REST conventions

## Invariants

### Money
1. Use minor units to represent money
2. Assume this app is operating in USD
3. Hence minor units are Cents
4. Use arithematic which doesn't lead to loss of money/precision

### Idempotency
1. API for order creation must accept an idempotency key
2. App will maintain the key record and determinsitc request hash associated with it
3. If key is reused -> return the same order id if has matches else throw error

### System
1. Data is stored in memory. You can have in memory structures in adapter class
2. Follow layered architecture
3. Perform validations before executing any operations
4. State transitions should be as per allowed transitions as per requirements stated above
5. Consistency is of utmost importance. The total portions = total available + total sold + total reserved. Never over/under sold

### Concurrency
1. Assume this API works for one user
2. Ensure concurrent request trying to read/write are handled properly through locking