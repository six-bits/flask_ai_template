# Problem Statement: Food Delivery Service with Daily Portion Limits & Per-User Carts

## Domain Overview
Food delivery domain for ordering dishes from a single restaurant with daily portion limits.
- Daily portion limits are strictly enforced across all users: portions are never oversold.
- **Per-User Carts**: The application supports multiple users. Each user maintains their own independent active shopping cart.
- **Pre-Seeded Users & Pre-Seeded Locks**: Known users are pre-seeded in the system by `user_id`. Dedicated locks are pre-seeded on a per-user basis.
- `user_id` is passed as part of requests (e.g. via `X-User-Id` header or request parameter).
- Placing an order for a user converts that user's active cart into an order and empties only that user's cart upon acceptance.

---

## Core Entities
1. **User**:
   - `user_id`: string (unique identifier)
   - `name`: string (e.g., "Alice", "Bob", "Charlie")

2. **Dish**:
   - `dish_id`: string
   - `name`: string (dish descriptor)
   - `price_per_unit`: integer (in minor units: cents, USD)
   - `total_portions`: integer (initial total daily portions)
   - `total_available_portions`: integer
   - `total_reserved_portions`: integer
   - `total_sold_portions`: integer

3. **OrderLineItem**:
   - `dish_id`: string
   - `name`: string
   - `units`: integer (positive count)
   - `price_per_unit`: integer (in minor units: cents)
   - `total_price`: integer (in minor units: cents, `units * price_per_unit`)

4. **OrderStatus**:
   - `ORDER_ACCEPTED`: Order placed successfully and portions reserved.
   - `ORDER_PREPARING`: Kitchen is preparing the order.
   - `ORDER_DELIVERING`: Order is out for delivery.
   - `ORDER_COMPLETED`: Terminal success state; order delivered to customer.
   - `ORDER_CANCELLED`: Terminal cancellation state; cancelled from `ORDER_ACCEPTED` or `ORDER_PREPARING`.
   - `ORDER_REJECTED`: Terminal rejection state; set if portions cannot be fulfilled at time of creation.

5. **Order**:
   - `order_id`: string
   - `user_id`: string (associated user)
   - `items`: list of `OrderLineItem`
   - `order_status`: `OrderStatus`
   - `total_amount`: integer (minor units)
   - `rejection_reason`: optional string

6. **Cart (Per-User)**:
   - Associated with a specific `user_id`.
   - `items`: list of `CartItem` (`dish_id`, `name`, `units`, `price_per_unit`, `total_price`)
   - `total_amount`: integer (minor units)
   - Emptying one user's cart does not affect other users' carts.

---

## Order Status Transitions & Lifecycle

### Allowed Transitions
1. $\text{ORDER\_ACCEPTED} \longrightarrow \text{ORDER\_PREPARING} \longrightarrow \text{ORDER\_DELIVERING} \longrightarrow \mathbf{\text{ORDER\_COMPLETED}}$
2. $\text{ORDER\_ACCEPTED} \longrightarrow \text{ORDER\_CANCELLED}$
3. $\text{ORDER\_PREPARING} \longrightarrow \text{ORDER\_CANCELLED}$
4. $\text{ORDER\_REJECTED}$ (assigned at creation if portions cannot be fulfilled)

### Terminal States
- `ORDER_COMPLETED`: Order successfully finished; portions marked as sold.
- `ORDER_CANCELLED`: Order cancelled; reserved portions returned to available.
- `ORDER_REJECTED`: Order rejected upon creation; no portions reserved.

---

## APIs Required
All cart and order creation requests require user context (via `X-User-Id` header or request parameter).

1. **List Dishes**: `GET /dishes` - List all dishes and portion availability stats across the restaurant.
2. **List Cart**: `GET /cart` (Requires `X-User-Id`) - Get the requesting user's active cart.
3. **Add Items to Cart**: `POST /cart/items` (Requires `X-User-Id`) - Add or increment items in the user's cart.
4. **Remove Items from Cart**: `DELETE /cart/items/{dish_id}` (Requires `X-User-Id`) - Remove or decrement items from the user's cart.
5. **Clear Cart**: `DELETE /cart` (Requires `X-User-Id`) - Explicitly empty the user's cart.
6. **Place Order**: `POST /orders` (Requires `X-User-Id` & `Idempotency-Key`) - Convert user's active cart into an order.
   - If accepted: order created with `ORDER_ACCEPTED`, portions reserved, and user's cart emptied.
   - If rejected (insufficient portions): order recorded with `ORDER_REJECTED`, user's cart retained.
   - If retried with existing idempotency key and matching request hash: return original order.
   - If key reused with conflicting request payload hash: return 409 conflict.
7. **List Orders**: `GET /orders` (Optional `X-User-Id` filter) - List orders (optionally filtered by user).
8. **Get Order by ID**: `GET /orders/{order_id}` - Retrieve order details.
9. **Transition Order State**: `POST /orders/{order_id}/transitions` - Advance order lifecycle state.

---

## Invariants & Constraints

### 1. Money
- Express all monetary values in integer minor units (USD Cents).
- No floating-point operations.

### 2. Idempotency
- `POST /orders` requires an idempotency key.
- Compute and persist deterministic SHA-256 request payload hash.
- Return original order on matching key + hash; reject on key reuse with different hash.

### 3. Inventory & Consistency
- Shared across all users: $\text{total\_portions} = \text{total\_available\_portions} + \text{total\_reserved\_portions} + \text{total\_sold\_portions}$.
- Portions can never be oversold or undersold regardless of concurrent orders from multiple users.

### 4. Adapter Storage & Concurrency Architecture
- Data stored in-memory using **typed record entities** (`UserRecordEntity`, `DishRecordEntity`, `CartRecordEntity`, `CartItemRecordEntity`, `OrderRecordEntity`, `OrderLineItemRecordEntity`, `IdempotencyRecordEntity`).
- **Pre-Seeded Users**: Users are pre-seeded in the adapter (`user_1`, `user_2`, `user_3`).
- **Pre-Seeded Per-User Locks**: Each user has a dedicated pre-seeded `threading.RLock()` in `_user_locks`.
- **Global Inventory Lock**: A dedicated `_inventory_lock` protects the shared dish portion counters.
- **Lock Ordering to Prevent Deadlocks**: Order placement strictly acquires `user_lock` first, then `_inventory_lock`.
