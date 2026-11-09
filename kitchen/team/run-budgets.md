# Run budgets and approvals

Model runs cost money and GPU time. Checks scale with the risk of a run, and each ticket that runs models works inside one budget the user approved once.

## Tiers

The designer writes the tier on the ticket. Without one, the highest tier that applies holds.

| Tier | When | Before starting | After finishing |
| --- | --- | --- | --- |
| Light | CPU only; or at most <!-- fill: light-tier call limit, e.g. 50 --> calls at no cost to a self-hosted service already running; no training | One start line on the ticket: the command, the output folder, the call count | The gate table and the report path |
| Medium | Pre-approved GPU inference or evaluation, as below | A run request with Scope, Model calls, Endpoint, Concurrency, and Expected time | The gate table, the report, and the paths of the run's record files |
| Heavy | Paid hosted APIs, training, service starts, more than <!-- fill: pre-approved limit, e.g. 500 --> calls<!-- module:model-text -->, or changed model-visible text<!-- /module:model-text --> | A full run request, and the verifier's spot check of a few requests | The gate table, the report, and the paths of the run's record files |

## Run requests

A full run request adds these fields right after the status block:

```text
Scope: <which data, how many samples, which stages>
Model calls: <count>
Endpoint: <model and where it is served>
Concurrency: <parallel requests, and the reading it came from>
Expected cost: <amount, and how it was computed>
GPU hours: <GPUs × hours>
Expected time: <duration, and the expected finish time>
```

- **Expected time**: the measured time per item, from a smoke run or the finished part, × the items left ÷ the concurrency actually in effect. Add the expected finish time in <!-- fill: the user's timezone -->. When progress runs more than 50% behind the estimate, post an updated one with the reason.
- **Concurrency**: fill the free capacity at request time, not a habitual number, and name the reading it came from. <!-- fill: the command that shows free capacity on the repo's services, or remove this sentence. -->

## What needs approval

- **Ticket budget**: a ticket that runs models states one budget for the whole ticket (model calls, expected cost), and the user approves it once on the ticket. The budget is an estimate, not a cap. Each stage starts as soon as its request is posted, the request gives the running total against the budget, and spending past the budget needs no new approval. When a stage's projection first passes 1.5 × the budget, the executor says so on the ticket and the run continues; the user hears it in the next summary. GPU hours are an estimate only: a run on our own GPUs is never stopped or re-approved for exceeding them.
- **Hosted API calls**: wait for the user's approval of the ticket budget.
- **GPU inference or evaluation of at most <!-- fill: pre-approved limit, e.g. 500 --> samples or model calls**: approved in advance when the code is merged on main, it runs on our GPUs ([long-running-jobs.md](long-running-jobs.md#compute)) against a service that is already running, and the request is posted before starting. Report the result when it finishes.
- **Training, service starts, a change of model or endpoint, and anything larger**: wait for the user's approval.

## Checking the numbers

Spending reported on a ticket is recomputed from the saved receipts with the repo's ledger script, never by hand. <!-- fill: the ledger script and how to call it, or remove this section if the repo keeps no receipts. -->
