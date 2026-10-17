# Runner monitoring

The runner exports Prometheus metrics at `GET /metrics` on its existing private
admin listener, alongside `/admin/status`. It requires the same bearer admin
token. Empty tokens disable access. The public generation listener has no metrics
route, and the orchestrator does not proxy it. Root Compose publishes admin on
host loopback; peers on attached Docker networks can still reach the authenticated
container listener. Do not expose admin publicly to make scraping convenient.

No Prometheus/Grafana stack, host exporter or GPU exporter is installed. Use the
operator's existing monitoring system with private connectivity to the listener.

| Metric                                 | Meaning                                                                      |
| -------------------------------------- | ---------------------------------------------------------------------------- |
| `video_runner_ready`                   | Engine running, registered, available and not switching                      |
| `video_runner_gpu_busy`                | Runner GPU lock held, including switching work                               |
| `video_runner_switching`               | Explicit switch or owned-engine recovery in progress                         |
| `video_runner_recovery_required`       | Uncertain engine state blocks reuse                                          |
| `video_runner_sessions`                | Current held persistent sessions                                             |
| `video_runner_jobs_total`              | Finished generation/delivery attempts by catalog model, delivery and outcome |
| `video_runner_job_duration_seconds`    | Histogram of generation plus delivery time after admission                   |
| `video_runner_refusals_total`          | Admission refusals by model and `busy`/`unavailable` reason                  |
| `video_runner_switches_total`          | Switch results by target model, `graceful`/`force` and outcome               |
| `video_runner_switch_duration_seconds` | Drain, activation and any rollback time                                      |
| `video_runner_engine_restarts_total`   | Owned-engine recovery attempts by model and success/failure                  |

Job outcomes are `completed`, `failed`, `cancelled`; completion means the runner
finished delivery, not that the client reviewed or acknowledged the video.
Invalid request bodies and refused jobs do not count as finished jobs. A task
cancelled before generation begins is not a generation/delivery attempt.
Switch outcomes are `succeeded`, `failed`, `cancelled`, `drain_timeout`; no-op
same-model requests do not count. Restart counters describe runner-triggered
owned-engine recovery, not every process/host/daemon restart. Counters reset
with the runner process; they are not durable accounting or billing records.

Labels use bounded catalog IDs, delivery modes and fixed outcomes/reasons.
Prompts, job/session IDs, tokens, URLs and arbitrary error strings are excluded.
There are no default process/environment collectors. Each runner owns its own
registry. GPU memory/utilization and host RAM remain the operator's exporter
responsibility. The controller retains its authenticated status/operation API.

For Prometheus running on the same host, adapt the
[scrape example](../../deploy/templates/prometheus.runner.example.yml). Its
credentials file must contain the runner admin token and be readable only by the
scraper's owner. A scraper in a container needs separate private connectivity;
its loopback is not the host's loopback. Alert on sustained unready state,
recovery required, repeated failures/refusals and engine recovery failures.
Model startup can legitimately take minutes; use appropriate observation windows.

Example PromQL for completed jobs and observed mean generation/delivery latency:

```promql
sum by (model, delivery) (rate(video_runner_jobs_total{outcome="completed"}[5m]))
sum(rate(video_runner_job_duration_seconds_sum[5m]))
  / sum(rate(video_runner_job_duration_seconds_count[5m]))
```

An empty/zero traffic window can yield no series or an undefined mean. The
histograms are measurements, not performance guarantees or visual-quality scores.
