"""/admin/stato-sistema: la pagina legge solo lo stato gia' calcolato dal
monitor (nessun integrity_check, nessuna scansione NAS, nessun restart di
servizi rifatto qui), quindi i test controllano soprattutto che sappia
restare in piedi e mostrare l'etichetta giusta qualunque cosa il monitor
abbia scritto l'ultima volta — compreso "non ha scritto niente"."""
import app.routers.admin as admin_router


def _monitor_finto(monkeypatch, dettagli, ultimo_check="2026-09-07T10:00:00"):
    """Sostituisce _leggi_stato_monitor con uno stato fisso, senza toccare
    il file vero ne' il monitor vero."""
    def finta():
        return {"ultimo_check": ultimo_check, "dettagli_ultimo": dettagli}
    monkeypatch.setattr(admin_router, "_leggi_stato_monitor", finta)


def _servizi_finti(monkeypatch, stato="active"):
    """Sostituisce _stato_servizio: nessuna chiamata vera a systemctl nei
    test, che devono restare veloci e non dipendere da cosa gira davvero
    sulla macchina che esegue la suite."""
    monkeypatch.setattr(admin_router, "_stato_servizio", lambda nome: stato)


# ---- 1. accesso da amministratore autenticato -----------------------------

def test_admin_autenticato_vede_la_pagina(client_admin, monkeypatch):
    _monitor_finto(monkeypatch, {"nas_ok": True, "nas_backup_ok": True})
    _servizi_finti(monkeypatch)
    r = client_admin.get("/admin/stato-sistema")
    assert r.status_code == 200
    assert "Stato del sistema" in r.text


# ---- 2. non autenticato: niente dati, reindirizzo al login -----------------

def test_non_autenticato_reindirizza_al_login(client):
    r = client.get("/admin/stato-sistema", follow_redirects=False)
    assert r.status_code in (302, 303, 307)
    assert "/admin/login" in r.headers.get("location", "")


# ---- 3. NAS lettura online: pillola OK -------------------------------------

def test_nas_lettura_online(client_admin, monkeypatch):
    _monitor_finto(monkeypatch, {"nas_ok": True, "nas_backup_ok": True})
    _servizi_finti(monkeypatch)
    r = client_admin.get("/admin/stato-sistema")
    assert r.status_code == 200
    assert "nas-ok" in r.text
    assert "ERRORE" not in r.text.split("NAS lettura")[1].split("NAS scrittura")[0]


# ---- 4. NAS offline: stato coerente, nessun crash --------------------------

def test_nas_lettura_offline_non_va_in_errore(client_admin, monkeypatch):
    _monitor_finto(monkeypatch, {"nas_ok": False, "nas_backup_ok": False})
    _servizi_finti(monkeypatch)
    r = client_admin.get("/admin/stato-sistema")
    assert r.status_code == 200
    assert "ERRORE" in r.text


# ---- 5. backup recente: OK --------------------------------------------------

def test_backup_recente_ok(client_admin, monkeypatch):
    _monitor_finto(monkeypatch, {
        "backup_db_ok": True, "backup_db_dettaglio": "12h fa, 156 nodi, 49373 foto",
    })
    _servizi_finti(monkeypatch)
    r = client_admin.get("/admin/stato-sistema")
    assert r.status_code == 200
    assert "12h fa, 156 nodi, 49373 foto" in r.text


# ---- 6. backup vecchio/fallito: warning/errore, non OK ---------------------

def test_backup_vecchio_non_e_ok(client_admin, monkeypatch):
    _monitor_finto(monkeypatch, {
        "backup_db_ok": False, "backup_db_dettaglio": "ultimo backup ha 40 ore",
    })
    _servizi_finti(monkeypatch)
    r = client_admin.get("/admin/stato-sistema")
    assert r.status_code == 200
    assert "ultimo backup ha 40 ore" in r.text
    assert "ERRORE" in r.text


# ---- 7. restore check fallito: mostrato correttamente ----------------------

def test_restore_check_fallito(client_admin, monkeypatch):
    _monitor_finto(monkeypatch, {
        "backup_db_integrity_ok": False,
        "backup_db_integrity_quando": "2026-09-07T03:00:00",
    })
    _servizi_finti(monkeypatch)
    r = client_admin.get("/admin/stato-sistema")
    assert r.status_code == 200
    assert "Restore check" in r.text
    assert "ERRORE" in r.text


# ---- 8. export configurazione non verificabile (NAS-scrittura giu') -------

def test_export_config_non_verificabile(client_admin, monkeypatch):
    _monitor_finto(monkeypatch, {
        "export_config_ok": None,
        "export_config_dettaglio": "NAS non raggiungibile: controllo saltato",
    })
    _servizi_finti(monkeypatch)
    r = client_admin.get("/admin/stato-sistema")
    assert r.status_code == 200
    assert "NON VERIFICABILE" in r.text
    assert "NAS non raggiungibile: controllo saltato" in r.text


# ---- 9. un servizio fallito: la pagina resta in piedi ----------------------

def test_servizio_fallito_non_fa_cadere_la_pagina(client_admin, monkeypatch):
    _monitor_finto(monkeypatch, {})
    monkeypatch.setattr(admin_router, "_stato_servizio",
                        lambda nome: "failed" if "backup" in nome else "active")
    r = client_admin.get("/admin/stato-sistema")
    assert r.status_code == 200
    assert "FALLITO" in r.text


# ---- 10. spazio disco: formattato, percentuale coerente --------------------

def test_spazio_disco_formattato(client_admin, monkeypatch):
    _monitor_finto(monkeypatch, {"disco_livello": "ok", "disco_liberi_pct": 62.3})
    _servizi_finti(monkeypatch)
    r = client_admin.get("/admin/stato-sistema")
    assert r.status_code == 200
    assert "/opt/photocarcifo" in r.text
    # 100 - 62.3 arrotondato a una cifra
    assert "37.7% usato" in r.text


# ---- extra: nessun dato dal monitor (file assente/timer fermo) ------------

def test_monitor_mai_girato_non_fa_cadere_la_pagina(client_admin, monkeypatch):
    def finta():
        return {}
    monkeypatch.setattr(admin_router, "_leggi_stato_monitor", finta)
    _servizi_finti(monkeypatch)
    r = client_admin.get("/admin/stato-sistema")
    assert r.status_code == 200
    assert "mai" in r.text


# ---- extra: pagina read-only, nessuna chiamata a systemctl start/stop -----

def test_nessun_controllo_start_stop_nei_sorgenti():
    """Verifica statica, non a runtime: il modulo non deve contenere
    chiamate a start/stop/restart di systemctl da questa pagina."""
    import inspect
    sorgente = inspect.getsource(admin_router)
    blocco = sorgente[sorgente.index("_STATO_MONITOR ="):]
    for vietato in ("systemctl\", \"start", "systemctl\", \"stop",
                    "systemctl\", \"restart"):
        assert vietato not in blocco
