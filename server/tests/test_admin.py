"""Administrator safeguards and last-active-admin protection (ADM-001..009)."""
import threading

from tests.conftest import auth, make_user, token


def test_promote_and_audit(client, db):
    a = make_user(db, "a")
    make_user(db, "admin2", role="admin")
    t = token(client, "admin2")
    r = client.put(f"/admin/users/{a.id}/role",
                   json={"role": "admin", "reason": "ok"}, headers=auth(client, t))
    assert r.status_code == 200
    audit = client.get("/admin/audit-events", headers=auth(client, t)).json()
    assert any(e["action"] == "user.role_changed" for e in audit)


def test_demote_last_admin_rejected(client, db):
    """Only the seed admin exists; demoting it must be rejected."""
    t = token(client, "admin")
    r = client.put("/admin/users/admin/admin/role".replace("/admin/admin", ""),
                   json={"role": "user", "reason": "x"}, headers=auth(client, t))
    # find the seed admin's id
    users = client.get("/admin/users", headers=auth(client, t)).json()
    seed = next(u for u in users if u["username"] == "admin")
    r = client.put(f"/admin/users/{seed['id']}/role",
                   json={"role": "user", "reason": "x"}, headers=auth(client, t))
    assert r.status_code == 409
    me = client.get("/auth/me", headers=auth(client, t)).json()
    assert me["role"] == "admin"


def test_disable_last_admin_rejected(client, db):
    """Only the seed admin exists; disabling it must be rejected."""
    t = token(client, "admin")
    users = client.get("/admin/users", headers=auth(client, t)).json()
    seed = next(u for u in users if u["username"] == "admin")
    r = client.put(f"/admin/users/{seed['id']}/status",
                   json={"status": "disabled", "reason": "x"}, headers=auth(client, t))
    assert r.status_code == 409


def test_concurrent_admin_removals_keep_one(client, db):
    """ADM-005/006: many concurrent attempts to remove the last two admins must
    leave at least one active administrator, even when requests interleave."""
    admin2 = make_user(db, "admin2", role="admin")
    t1 = token(client, "admin")
    t2 = token(client, "admin2")
    users = client.get("/admin/users", headers=auth(client, t1)).json()
    seed = next(u for u in users if u["username"] == "admin")
    results = []

    def attempt(uid, tok):
        r = client.put(f"/admin/users/{uid}/role",
                       json={"role": "user", "reason": "x"}, headers=auth(client, tok))
        results.append(r.status_code)

    threads = [threading.Thread(target=attempt, args=(admin2.id, t1)),
               threading.Thread(target=attempt, args=(seed['id'], t2))]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    # Invariant: at least one active administrator survives.
    admins = client.get("/admin/users", headers=auth(client, t1)).json()
    active_admins = [u for u in admins if u["role"] == "admin" and u["status"] == "active"]
    assert len(active_admins) >= 1
