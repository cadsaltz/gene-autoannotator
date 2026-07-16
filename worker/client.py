import httpx


class CoordinatorClient:
    def __init__(self, config, http_client=None):
        self._config = config
        self._http = http_client or httpx.Client(base_url=config.coordinator_url, timeout=60.0)
        self._auth = {"Authorization": f"Bearer {config.worker_api_token}"}
        self.worker_id = None

    def register(self):
        response = self._http.post(
            "/workers/register",
            headers=self._auth,
            json={
                "worker_name": self._config.worker_name,
                "hostname": self._config.hostname,
                "agent_version": self._config.agent_version,
                "total_memory_bytes": self._config.total_memory_bytes,
                "dedicated_memory_bytes": self._config.dedicated_memory_bytes,
                "max_slots": self._config.max_slots,
                "ollama_models": [],
            },
        )
        response.raise_for_status()
        self.worker_id = response.json()["worker_id"]
        return self.worker_id

    def heartbeat(self, active_jobs, free_slots, memory_available_bytes, cpu_percent, state):
        response = self._http.post(
            f"/workers/{self.worker_id}/heartbeat",
            headers=self._auth,
            json={
                "active_jobs": active_jobs,
                "free_slots": free_slots,
                "memory_available_bytes": memory_available_bytes,
                "cpu_percent": cpu_percent,
                "state": state,
            },
        )
        response.raise_for_status()
        return response.json()

    def claim(self, free_slots):
        response = self._http.post(
            f"/workers/{self.worker_id}/claim", headers=self._auth, json={"free_slots": free_slots}
        )
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return response.json()

    def progress(self, job_id, current_step, **fields):
        payload = {"current_step": current_step}
        for key in (
            "phase",
            "sections_done",
            "sections_total",
            "papers_done",
            "papers_total",
            "pass_name",
        ):
            value = fields.get(key)
            if value is not None:
                payload[key] = value
        self._http.patch(
            f"/jobs/{job_id}/progress", headers=self._auth, json=payload
        ).raise_for_status()

    def complete(self, job_id, result):
        self._http.post(
            f"/jobs/{job_id}/complete", headers=self._auth, json={"result": result}
        ).raise_for_status()

    def fail(self, job_id, error, retryable):
        self._http.post(
            f"/jobs/{job_id}/fail",
            headers=self._auth,
            json={"error": error, "retryable": retryable},
        ).raise_for_status()
