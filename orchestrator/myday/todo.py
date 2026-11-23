"""Microsoft To Do through Graph, with the brief's Outlook login (delegated, your account only).

Scope ``Tasks.ReadWrite`` (``orchestrator.brief.sources.outlook.TODO_SCOPES``). Add it in Entra
(API permissions → Microsoft Graph → Delegated → Tasks.ReadWrite), then sign in once more:
``python -m orchestrator.brief auth microsoft``.

Due dates are whole days. To Do's own apps store them as midnight UTC of that day, so they are
written that way here and read back as the calendar date in your time zone.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from orchestrator.brief.net import Http, HttpError

from .errors import MyDayError

GRAPH = "https://graph.microsoft.com/v1.0"


@dataclass(frozen=True)
class Task:
    id: str
    list_id: str
    title: str
    due: date | None
    done: bool
    important: bool = False
    completed_on: date | None = None

    @property
    def key(self) -> str:
        return f"{self.list_id}|{self.id}"


@dataclass(frozen=True)
class Step:
    id: str
    title: str
    done: bool


def split_key(key: str) -> tuple[str, str]:
    list_id, _, task_id = key.partition("|")
    return list_id, task_id


def _date(value: dict | None, tz: ZoneInfo) -> date | None:
    if not value or not value.get("dateTime"):
        return None
    stamp = datetime.fromisoformat(value["dateTime"][:19])
    zone = value.get("timeZone") or "UTC"
    if zone.upper() == "UTC":
        # midnight UTC = a date-only value from To Do; anything else is a real instant
        return stamp.date() if stamp.time() == datetime.min.time() else stamp.replace(tzinfo=UTC).astimezone(tz).date()
    return stamp.date()


def _day_value(day: date) -> dict:
    return {"dateTime": f"{day.isoformat()}T00:00:00", "timeZone": "UTC"}


class Todo:
    def __init__(self, http: Http, token: Callable[[], str], tz: ZoneInfo) -> None:
        self.http = http
        self._token = token
        self.tz = tz
        self._lists: dict[str, str] | None = None
        self._default = ""

    def _call(self, method: str, path: str, **kw) -> dict:
        url = path if path.startswith("https://") else GRAPH + path
        try:
            response = self.http.request(method, url, headers={"Authorization": f"Bearer {self._token()}"}, **kw)
        except HttpError as exc:
            hint = (" (add Tasks.ReadWrite in Entra, then sign in again: python -m orchestrator.brief auth microsoft)"
                    if exc.status in (401, 403) else "")
            raise MyDayError(f"To Do {method} {path.split('?')[0][:60]}: HTTP {exc.status}{hint}") from None
        return response.json() if response.body else {}

    def _pages(self, path: str, params: dict) -> list[dict]:
        rows: list[dict] = []
        page = self._call("GET", path, params=params)
        while True:
            rows += page.get("value") or []
            link = page.get("@odata.nextLink")
            if not link or len(rows) >= 1000:
                return rows
            page = self._call("GET", link)

    # ---- lists ---------------------------------------------------------------------------------

    def _load_lists(self) -> dict[str, str]:
        if self._lists is None:
            rows = self._pages("/me/todo/lists", {"$top": 100})
            self._lists = {r["displayName"]: r["id"] for r in rows}
            self._default = next((r["id"] for r in rows if r.get("wellknownListName") == "defaultList"), "")
        return self._lists

    def list_id(self, name: str) -> str:
        """The list called ``name`` (created if missing); empty name → your default list."""
        lists = self._load_lists()
        if not name:
            if not self._default:
                raise MyDayError("To Do has no default list; set lists.tasks in myday.yaml.")
            return self._default
        if name not in lists:
            lists[name] = self._call("POST", "/me/todo/lists", json_body={"displayName": name})["id"]
        return lists[name]

    # ---- tasks ---------------------------------------------------------------------------------

    def _task(self, list_id: str, row: dict) -> Task:
        return Task(row["id"], list_id, row.get("title") or "", _date(row.get("dueDateTime"), self.tz),
                    row.get("status") == "completed", row.get("importance") == "high",
                    _date(row.get("completedDateTime"), self.tz))

    def open_tasks(self, list_id: str) -> list[Task]:
        rows = self._pages(f"/me/todo/lists/{list_id}/tasks", {"$filter": "status ne 'completed'", "$top": 100})
        return [self._task(list_id, r) for r in rows]

    def get(self, list_id: str, task_id: str) -> Task | None:
        """None when the task was deleted."""
        try:
            return self._task(list_id, self._call("GET", f"/me/todo/lists/{list_id}/tasks/{task_id}"))
        except MyDayError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise

    def add(self, list_id: str, title: str, due: date | None, *, remind: datetime | None = None,
            important: bool = False, note: str = "") -> Task:
        body: dict = {"title": title, "importance": "high" if important else "normal"}
        if due:
            body["dueDateTime"] = _day_value(due)
        if remind:
            body["isReminderOn"] = True
            body["reminderDateTime"] = {"dateTime": remind.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
                                        "timeZone": "UTC"}
        if note:
            body["body"] = {"content": note, "contentType": "text"}
        return self._task(list_id, self._call("POST", f"/me/todo/lists/{list_id}/tasks", json_body=body))

    def complete(self, list_id: str, task_id: str) -> None:
        self._call("PATCH", f"/me/todo/lists/{list_id}/tasks/{task_id}", json_body={"status": "completed"})

    def set_due(self, list_id: str, task_id: str, due: date | None) -> None:
        self._call("PATCH", f"/me/todo/lists/{list_id}/tasks/{task_id}",
                   json_body={"dueDateTime": _day_value(due) if due else None})

    def set_important(self, list_id: str, task_id: str, important: bool) -> None:
        self._call("PATCH", f"/me/todo/lists/{list_id}/tasks/{task_id}",
                   json_body={"importance": "high" if important else "normal"})

    # ---- steps (goal milestones) ---------------------------------------------------------------

    def steps(self, list_id: str, task_id: str) -> list[Step]:
        rows = self._pages(f"/me/todo/lists/{list_id}/tasks/{task_id}/checklistItems", {})
        return [Step(r["id"], r.get("displayName") or "", bool(r.get("isChecked"))) for r in rows]

    def add_step(self, list_id: str, task_id: str, title: str) -> Step:
        row = self._call("POST", f"/me/todo/lists/{list_id}/tasks/{task_id}/checklistItems",
                         json_body={"displayName": title})
        return Step(row["id"], title, False)

    def check_step(self, list_id: str, task_id: str, step_id: str) -> None:
        self._call("PATCH", f"/me/todo/lists/{list_id}/tasks/{task_id}/checklistItems/{step_id}",
                   json_body={"isChecked": True})


def reminder_at(day: date, hour: int, tz: ZoneInfo) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=tz)


def week_end(today: date) -> date:
    return today + timedelta(days=6 - today.weekday())
