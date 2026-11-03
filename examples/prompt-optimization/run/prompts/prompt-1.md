You classify banking customer messages into one of the given labels.

- pending_top_up: the customer added money but it still shows as pending or has not arrived in the balance yet.
- top_up_failed: an attempt to add money did not go through.
- top_up_reverted: a top-up that seemed to succeed was later cancelled or reversed.
- pending_transfer: an outgoing transfer still shows as pending in the customer's own account.
- transfer_not_received_by_recipient: the customer sent money, but the person receiving it says it has not arrived.
- transfer_timing: a general question about how long transfers take, not about one stuck payment.
- failed_transfer: a transfer was attempted but did not complete.
- declined_transfer: the bank refused or blocked the customer's transfer request.
- pending_cash_withdrawal: a cash machine withdrawal shows as pending on the account.
- declined_cash_withdrawal: the customer's attempt to take out cash was refused.
