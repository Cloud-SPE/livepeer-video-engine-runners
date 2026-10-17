"""Per-runner, bounded-label metrics exposed only on the private admin app."""

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram


class Metrics:
    def __init__(self, runner):
        self.registry = CollectorRegistry()
        gauges = {
            "ready": lambda: bool(
                runner.available
                and runner.supervisor.running
                and runner.registrations
                and not runner.switching
            ),
            "gpu_busy": runner.gpu.locked,
            "switching": lambda: runner.switching,
            "recovery_required": lambda: runner.needs_reset,
            "sessions": lambda: len(runner.sessions),
        }
        for name, value in gauges.items():
            Gauge(
                f"video_runner_{name}", f"Runner {name}.", registry=self.registry
            ).set_function(value)
        self.jobs = Counter(
            "video_runner_jobs_total",
            "Finished generation/delivery attempts.",
            ("model", "delivery", "outcome"),
            registry=self.registry,
        )
        self.refusals = Counter(
            "video_runner_refusals_total",
            "Admission refusals, excluding invalid request bodies.",
            ("model", "reason"),
            registry=self.registry,
        )
        self.switches = Counter(
            "video_runner_switches_total",
            "Finished model switches, including drain refusals.",
            ("model", "mode", "outcome"),
            registry=self.registry,
        )
        self.restarts = Counter(
            "video_runner_engine_restarts_total",
            "Owned-engine recovery attempts; not host or daemon restarts.",
            ("model", "outcome"),
            registry=self.registry,
        )
        self.switch_duration = Histogram(
            "video_runner_switch_duration_seconds",
            "Drain, activation and rollback time.",
            ("model", "mode", "outcome"),
            buckets=(1, 5, 30, 60, 120, 300, 600, 1800, 3600),
            registry=self.registry,
        )
        self.duration = Histogram(
            "video_runner_job_duration_seconds",
            "Generation and delivery time after admission.",
            ("model", "delivery", "outcome"),
            buckets=(1, 5, 15, 30, 60, 120, 300, 600, 1200, 3600, 7200),
            registry=self.registry,
        )
