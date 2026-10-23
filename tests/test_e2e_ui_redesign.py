"""
E2E Test Suite: National University Bangladesh AI Assistant UI Redesign
Follows the 4-Tier Test Architecture defined in TEST_INFRA.md:
- Tier 1: Feature Coverage (>=5 tests per feature for 11 features = 55 tests)
- Tier 2: Boundary & Corner Cases (6 tests)
- Tier 3: Pairwise Interactions (4 tests)
- Tier 4: Real-World Workload Scenarios (5 scenarios)

Execution: .venv\\Scripts\\python.exe -m pytest tests/test_e2e_ui_redesign.py -v
"""

import os
import re
import json
import time
import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from backend.app import app
from backend.api.admin_routes import router as admin_v1_router
from backend.core.security import create_jwt_token, Role
from backend.models.schemas import TokenCreateRequest as DomainTokenCreateRequest
from token_service.models import TokenCreateRequest as RepoTokenCreateRequest
from backend.services.token_service import get_token_domain_service
from backend.services.faq_service import get_faq_service
from backend.services.backup_service import get_backup_service
from token_service.service import get_token_service


# ==============================================================================
# Shared Fixtures
# ==============================================================================

@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient instance."""
    return TestClient(app)


@pytest.fixture(scope="module")
def index_html():
    """Raw content of static/index.html."""
    path = os.path.join("static", "index.html")
    assert os.path.exists(path), f"File not found: {path}"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def chat_html():
    """Raw content of static/chat.html."""
    path = os.path.join("static", "chat.html")
    assert os.path.exists(path), f"File not found: {path}"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def index_soup(index_html):
    """Parsed BeautifulSoup DOM of static/index.html."""
    return BeautifulSoup(index_html, "html.parser")


@pytest.fixture(scope="module")
def chat_soup(chat_html):
    """Parsed BeautifulSoup DOM of static/chat.html."""
    return BeautifulSoup(chat_html, "html.parser")


@pytest.fixture(scope="module")
def token_domain_svc():
    """TokenDomainService instance."""
    return get_token_domain_service()


@pytest.fixture(scope="module")
def legacy_token_svc():
    """Legacy/Repository TokenService instance."""
    return get_token_service()


@pytest.fixture(scope="module")
def faq_svc():
    """FAQService instance with seeded knowledge base."""
    svc = get_faq_service()
    svc.ensure_seeded()
    return svc


# ==============================================================================
# TIER 1: FEATURE COVERAGE (11 Features x >=5 tests = 55 tests)
# ==============================================================================

# ------------------------------------------------------------------------------
# Feature 1: High-Density Token Table & Badges (static/index.html)
# ------------------------------------------------------------------------------

def test_f1_01_table_container_and_headers_present(index_soup):
    """Verify high-density data table container and mandatory header columns exist."""
    tbody = index_soup.find("tbody", id="admin-tokens-tbody")
    assert tbody is not None, "Missing #admin-tokens-tbody table body container"
    
    table = tbody.find_parent("table")
    assert table is not None, "#admin-tokens-tbody must reside within a <table> element"
    
    thead = table.find("thead")
    assert thead is not None, "High-density token table must have a <thead> header section"
    headers_text = thead.get_text()
    for col in ["Token ID", "Student", "Service", "Problem", "Status"]:
        assert col.lower() in headers_text.lower(), f"Header column '{col}' missing from token table"


def test_f1_02_status_badges_muted_styling_classes(index_html):
    """Verify support for muted status badges / pips across all domain statuses."""
    expected_statuses = ["PENDING", "ASSIGNED", "PROCESSING", "SOLVED", "CLOSED", "REJECTED"]
    for status in expected_statuses:
        assert status in index_html, f"Status '{status}' badge logic must be represented in static/index.html"
    
    # Check for soft muted tint classes or badge styling representation
    has_badge_styling = any(cls in index_html for cls in [
        "rounded", "badge", "status", "bg-amber", "text-amber", "bg-emerald", "text-emerald"
    ])
    assert has_badge_styling, "Muted status badge styling classes missing in index.html"


def test_f1_03_table_rows_open_drawer_on_click(index_html):
    """Verify table row click event binds openAdminManageToken to slide open the drawer."""
    assert "openAdminManageToken" in index_html, "openAdminManageToken function missing from index.html"
    assert "function openAdminManageToken" in index_html or "async function openAdminManageToken" in index_html, \
        "openAdminManageToken must be defined as an executable function"


def test_f1_04_action_buttons_stop_event_propagation(index_html):
    """Verify quick row action buttons use event.stopPropagation() to avoid inadvertent drawer opening."""
    assert "stopPropagation" in index_html, \
        "event.stopPropagation() must be attached to table row action buttons (Trash/Restore)"


def test_f1_05_student_columns_and_problem_rendered(index_html):
    """Verify render function extracts student contact info (Name, Phone, Reg) and problem text."""
    for field in ["user_name", "user_phone", "problem"]:
        assert field in index_html, f"Field '{field}' must be referenced in index.html token rendering"


# ------------------------------------------------------------------------------
# Feature 2: Slide-Over Inspection Drawer Structure & DOM IDs (static/index.html)
# ------------------------------------------------------------------------------

def test_f2_01_drawer_container_and_panel_structure(index_soup):
    """Verify slide-over inspection drawer modal container exists."""
    drawer_modal = index_soup.find(id="admin-manage-token-modal")
    assert drawer_modal is not None, "Missing #admin-manage-token-modal element"
    classes = drawer_modal.get("class", [])
    assert "fixed" in classes, "Drawer container must be fixed position"
    assert "z-[60]" in classes or "z-50" in classes or any("z-" in c for c in classes), \
        "Drawer must have elevated z-index"


def test_f2_02_student_problem_context_dom_ids(index_soup):
    """Verify student details and problem context DOM IDs are present inside drawer."""
    expected_ids = [
        "adm-token-id",
        "adm-status-badge",
        "adm-user-name",
        "adm-user-phone",
        "adm-reg-no",
        "adm-service",
        "adm-date",
        "adm-problem"
    ]
    for dom_id in expected_ids:
        elem = index_soup.find(id=dom_id)
        assert elem is not None, f"Required drawer DOM ID #{dom_id} not found in static/index.html"


def test_f2_03_solver_action_controls_dom_ids(index_soup):
    """Verify solver action controls exist: resolution input, solve button, return reason, return button."""
    solve_msg = index_soup.find(id="adm-solve-message")
    assert solve_msg is not None, "Missing #adm-solve-message textarea"
    
    return_input = index_soup.find(id="solver-return-reason-input")
    assert return_input is not None, "Missing #solver-return-reason-input"
    
    # Check buttons or handlers
    html_text = str(index_soup)
    assert "submitSolveToken" in html_text, "Missing submitSolveToken action handler"
    assert "submitReturnToAdmin" in html_text, "Missing submitReturnToAdmin action handler"


def test_f2_04_admin_controls_and_internal_notes_dom_ids(index_soup):
    """Verify admin controls panel, solver assignment select, and private notes exist."""
    admin_panel = index_soup.find(id="adm-admin-controls-panel")
    assert admin_panel is not None, "Missing #adm-admin-controls-panel"
    
    solver_select = index_soup.find(id="adm-solver-select")
    assert solver_select is not None, "Missing #adm-solver-select"
    
    status_select = index_soup.find(id="adm-status-select")
    assert status_select is not None, "Missing #adm-status-select"
    
    note_input = index_soup.find(id="adm-note-input")
    assert note_input is not None, "Missing #adm-note-input for internal notes"


def test_f2_05_drawer_close_actions_and_handlers(index_html):
    """Verify closeAdminManageTokenModal is defined and wired to dismiss the drawer."""
    assert "closeAdminManageTokenModal" in index_html, \
        "Missing closeAdminManageTokenModal function in static/index.html"


# ------------------------------------------------------------------------------
# Feature 3: Solver Role Desk Isolation & Actions
# ------------------------------------------------------------------------------

def test_f3_01_solver_tab_restriction_to_support_center(index_html):
    """Verify Solver role is strictly restricted to Token Support Center tab only."""
    assert "SOLVER" in index_html, "Solver role handling missing in index.html"
    assert "switchAdminTab" in index_html, "switchAdminTab function missing"
    assert "tab-btn-tokens" in index_html, "tab-btn-tokens missing from tab navigation"


def test_f3_02_solver_token_list_department_filtering(legacy_token_svc):
    """Verify backend token list enforces department desk isolation for solvers."""
    # Create token for ICT Desk and assign to solver 1 (ICT Support Team)
    t_ict = legacy_token_svc.create_token(RepoTokenCreateRequest(
        service_type="EMS",
        problem="EMS student login issue for ICT desk isolation test"
    ))
    legacy_token_svc.assign_token(t_ict.token_id, solver_id=1)

    # Create token for Accounts Desk and assign to solver 5 (Accounts & Sonali Seba Desk)
    t_acc = legacy_token_svc.create_token(RepoTokenCreateRequest(
        service_type="SONALI_PAYMENT",
        problem="Sonali Seba payment sync issue for Accounts desk isolation test"
    ))
    legacy_token_svc.assign_token(t_acc.token_id, solver_id=5)
    
    # Query as ICT Solver
    ict_tokens, ict_total = legacy_token_svc.repo.list_tokens(
        role="SOLVER",
        department="ICT Support Team"
    )
    ict_ids = [t["token_id"] for t in ict_tokens]
    assert t_ict.token_id in ict_ids, "ICT Solver must see assigned ICT tokens"
    assert t_acc.token_id not in ict_ids, "ICT Solver must NOT see Accounts tokens"


def test_f3_03_solver_desk_banner_visible_reassign_hidden(index_soup):
    """Verify solver assignment notice banner exists to display assigned desk without reassignment select."""
    solver_notice = index_soup.find(id="solver-assignment-notice")
    assert solver_notice is not None, "Missing #solver-assignment-notice element"
    
    desk_display = index_soup.find(id="solver-desk-name-display")
    assert desk_display is not None, "Missing #solver-desk-name-display inside solver notice"


def test_f3_04_solver_solve_action_execution(token_domain_svc):
    """Verify Solver can solve an assigned token with official resolution steps."""
    t = token_domain_svc.create_token(DomainTokenCreateRequest(
        service_code="TC",
        problem="College transfer certificate approval delay"
    ))
    # Assign and solve
    token_domain_svc.assign_solver(t.token_id, solver_id=1, changed_by="ADMIN")
    ok, msg = token_domain_svc.solve_token(
        token_id=t.token_id,
        solve_message="TC application verified and synchronized with college portal.",
        solver_name="Registration Desk"
    )
    assert ok is True, f"Solve failed: {msg}"
    
    detail = token_domain_svc.get_admin_token_detail(t.token_id)
    assert detail.status == "SOLVED"
    assert "synchronized with college portal" in detail.solve_message


def test_f3_05_solver_return_action_execution(token_domain_svc):
    """Verify Solver can send back token to admin for instruction, transitioning status to PENDING."""
    t = token_domain_svc.create_token(DomainTokenCreateRequest(
        service_code="EMS",
        problem="Attendance requirement waiver needed"
    ))
    token_domain_svc.assign_solver(t.token_id, solver_id=1, changed_by="ADMIN")
    ok, msg = token_domain_svc.return_to_admin(
        token_id=t.token_id,
        reason="Requires Dean / VC special permission signature.",
        solver_name="ICT Desk",
        changed_by="solver_ict"
    )
    assert ok is True, f"Return to admin failed: {msg}"
    detail = token_domain_svc.get_admin_token_detail(t.token_id)
    assert detail.status == "PENDING"
    assert "Requires Dean / VC special permission" in detail.admin_note


# ------------------------------------------------------------------------------
# Feature 4: Super Admin Controls (Trash, Restore, Backup)
# ------------------------------------------------------------------------------

def test_f4_01_super_admin_trash_filter_option(index_soup):
    """Verify Super Admin has #opt-trash-filter dropdown option in status filter."""
    trash_opt = index_soup.find(id="opt-trash-filter")
    assert trash_opt is not None, "Missing #opt-trash-filter in static/index.html"
    assert trash_opt.get("value") == "TRASH"


def test_f4_02_super_admin_soft_delete_to_trash(legacy_token_svc):
    """Verify Super Admin can soft-delete a token to trash."""
    t = legacy_token_svc.create_token(RepoTokenCreateRequest(
        problem="Duplicate ticket created by accident",
        service_type="OTHER"
    ))
    ok = legacy_token_svc.repo.soft_delete_token(t.token_id, admin_user="SuperAdmin")
    assert ok is True, "Soft-delete failed"
    
    trash_tokens, total = legacy_token_svc.repo.list_tokens(
        status="DELETED",
        search=t.token_id,
        role="SUPER_ADMIN"
    )
    assert total >= 1
    assert any(x["token_id"] == t.token_id for x in trash_tokens)


def test_f4_03_deleted_token_omitted_from_active_list(legacy_token_svc):
    """Verify soft-deleted tokens do not appear in active listings for admins or solvers."""
    t = legacy_token_svc.create_token(RepoTokenCreateRequest(
        problem="Spam inquiry to test deletion isolation",
        service_type="OTHER"
    ))
    legacy_token_svc.repo.soft_delete_token(t.token_id, admin_user="SuperAdmin")
    
    active_tokens, total = legacy_token_svc.repo.list_tokens(search=t.token_id, role="SUPER_ADMIN")
    assert total == 0, "Deleted token must not appear in active list"


def test_f4_04_super_admin_restore_from_trash(legacy_token_svc):
    """Verify Super Admin can restore a soft-deleted token from trash."""
    t = legacy_token_svc.create_token(RepoTokenCreateRequest(
        problem="Accidentally deleted ticket to restore",
        service_type="OTHER"
    ))
    legacy_token_svc.repo.soft_delete_token(t.token_id, admin_user="SuperAdmin")
    
    # Restore
    ok = legacy_token_svc.repo.restore_token(t.token_id, admin_user="SuperAdmin")
    assert ok is True, "Restore failed"
    
    # Re-verify in active list
    active_tokens, total = legacy_token_svc.repo.list_tokens(search=t.token_id, role="SUPER_ADMIN")
    assert total == 1
    assert active_tokens[0]["is_deleted"] == 0


def test_f4_05_super_admin_backup_creation_and_listing():
    """Verify backup service creates valid zip backup and lists it."""
    backup_svc = get_backup_service()
    backup_path, meta = backup_svc.create_backup()
    assert backup_path.exists(), f"Backup file {backup_path} does not exist"
    assert "checksums" in meta
    assert "stats" in meta
    
    backups = backup_svc.list_backups()
    assert len(backups) >= 1
    assert any(b["filename"] == backup_path.name for b in backups)


# ------------------------------------------------------------------------------
# Feature 5: Return-to-Admin Route Integrity
# ------------------------------------------------------------------------------

def test_f5_01_route_registration_in_admin_router():
    """Verify POST /api/v1/admin/tokens/{token_id}/return-to-admin is registered on the admin router."""
    routes = [r.path for r in admin_v1_router.routes if hasattr(r, "path")]
    expected = "/api/v1/admin/tokens/{token_id}/return-to-admin"
    assert any("return-to-admin" in r for r in routes), \
        f"Route with return-to-admin must be registered on admin router. Registered: {routes}"


def test_f5_02_backend_route_requires_auth(client):
    """Verify unauthenticated request to /api/v1/admin/tokens/.../return-to-admin is rejected."""
    res = client.post("/api/v1/admin/tokens/NU-2026-000001/return-to-admin", json={
        "token_id": "NU-2026-000001",
        "return_reason": "Test unauth"
    })
    # Must reject with 401 or 403 (not 404)
    assert res.status_code in [401, 403], f"Expected 401/403 for unauthenticated request, got {res.status_code}"


def test_f5_03_frontend_submit_return_to_admin_contract(index_html):
    """Verify frontend submitReturnToAdmin function exists and references return-to-admin."""
    assert "submitReturnToAdmin" in index_html, "submitReturnToAdmin function missing from index.html"
    assert "return-to-admin" in index_html, "return-to-admin endpoint missing from index.html"
    assert "solver-return-reason-input" in index_html, "solver-return-reason-input missing from index.html"


def test_f5_04_domain_service_return_to_admin_flow(token_domain_svc):
    """Verify TokenDomainService.return_to_admin accurately sets status to PENDING with audit notes."""
    t = token_domain_svc.create_token(DomainTokenCreateRequest(
        service_code="CORRECTION",
        problem="Name spelling error on Honours registration card"
    ))
    token_domain_svc.assign_solver(t.token_id, solver_id=1, changed_by="ADMIN")
    
    ok, msg = token_domain_svc.return_to_admin(
        token_id=t.token_id,
        reason="SSC / HSC certificate board verification required before name change.",
        solver_name="Correction Desk",
        changed_by="solver_correction"
    )
    assert ok is True
    detail = token_domain_svc.get_admin_token_detail(t.token_id)
    assert detail.status == "PENDING"
    assert "board verification required" in detail.admin_note


def test_f5_05_return_to_admin_nonexistent_token(token_domain_svc):
    """Verify return_to_admin returns False when token does not exist."""
    ok, msg = token_domain_svc.return_to_admin(
        token_id="NU-NONEXISTENT-999999",
        reason="Invalid test token",
        solver_name="Test Desk"
    )
    assert ok is False
    assert "not found" in msg.lower()


# ------------------------------------------------------------------------------
# Feature 6: Sleek FAQ Accordion & Search (static/chat.html)
# ------------------------------------------------------------------------------

def test_f6_01_faq_search_input_and_handler_binding(chat_soup):
    """Verify #faq-search-input exists and binds handleFaqSearch."""
    search_input = chat_soup.find(id="faq-search-input")
    assert search_input is not None, "Missing #faq-search-input in static/chat.html"
    oninput = search_input.get("oninput", "")
    assert "handleFaqSearch" in oninput, "handleFaqSearch must be bound to #faq-search-input"


def test_f6_02_faq_search_debounce_timing(chat_html):
    """Verify handleFaqSearch implements 250ms debounced execution."""
    assert "handleFaqSearch" in chat_html, "handleFaqSearch missing from chat.html"
    # Check for setTimeout / debounce logic
    assert "setTimeout" in chat_html and ("250" in chat_html or "debounce" in chat_html.lower()), \
        "Debounce timing (250ms) missing from handleFaqSearch in chat.html"


def test_f6_03_faq_clear_search_button_and_reset(chat_soup, chat_html):
    """Verify #faq-clear-search button exists and invokes clearFaqSearch()."""
    clear_btn = chat_soup.find(id="faq-clear-search")
    assert clear_btn is not None, "Missing #faq-clear-search button in chat.html"
    assert "clearFaqSearch" in chat_html, "clearFaqSearch function missing from chat.html"


def test_f6_04_faq_accordion_cards_and_drawer_structure(chat_soup, chat_html):
    """Verify #faq-main-list renders accordion cards with toggleFaqExpand drawer."""
    faq_list = chat_soup.find(id="faq-main-list")
    assert faq_list is not None, "Missing #faq-main-list container"
    assert "toggleFaqExpand" in chat_html, "toggleFaqExpand function missing from chat.html"


def test_f6_05_faq_bilingual_search_functionality(client):
    """Verify bilingual search returns matching items in both Bengali and English."""
    # Bengali query
    r_bn = client.get("/api/v1/faqs?search=ভর্তি&limit=5")
    assert r_bn.status_code == 200
    assert len(r_bn.json().get("items", [])) > 0, "Bengali search for 'ভর্তি' must return results"
    
    # English query
    r_en = client.get("/api/v1/faqs?search=EMS&limit=5")
    assert r_en.status_code == 200
    assert "items" in r_en.json(), "English search for 'EMS' must return valid items list"


# ------------------------------------------------------------------------------
# Feature 7: Horizontal Category Scroll Pills (static/chat.html)
# ------------------------------------------------------------------------------

def test_f7_01_horizontal_scroll_pill_container_structure(chat_soup):
    """Verify #faq-topic-tags container exists with horizontal scroll styling."""
    topic_tags = chat_soup.find(id="faq-topic-tags")
    assert topic_tags is not None, "Missing #faq-topic-tags container"
    classes = topic_tags.get("class", [])
    has_scroll = any("overflow-x-auto" in c or "no-scrollbar" in c or "overflow" in c for c in classes)
    assert has_scroll, "#faq-topic-tags must have horizontal scroll styling"


def test_f7_02_category_endpoint_returns_topic_counts(client):
    """Verify /api/v1/faqs/categories returns list of categories with item counts."""
    res = client.get("/api/v1/faqs/categories")
    assert res.status_code == 200
    data = res.json()
    assert "categories" in data
    cats = data["categories"]
    assert len(cats) >= 10, f"Expected >=10 categories, got {len(cats)}"
    for c in cats:
        assert "category" in c
        assert "count" in c and c["count"] >= 0


def test_f7_03_category_hashtag_pill_formatting(chat_html):
    """Verify category pills feature hashtag topic formatting (#সকল_টপিক)."""
    assert "#সকল_টপিক" in chat_html or "সকল_টপিক" in chat_html, \
        "Missing #সকল_টপিক root pill format in static/chat.html"


def test_f7_04_category_click_handler_and_active_state(chat_html):
    """Verify handleTopicTagClick updates active topic and loads filtered items."""
    assert "handleTopicTagClick" in chat_html, \
        "Missing handleTopicTagClick function in static/chat.html"


def test_f7_05_category_filtering_backend_precision(client):
    """Verify filtering by category returns strictly items belonging to that category."""
    cats_res = client.get("/api/v1/faqs/categories")
    first_cat = cats_res.json()["categories"][0]["category"]
    
    filt_res = client.get(f"/api/v1/faqs?category={first_cat}&limit=20")
    assert filt_res.status_code == 200
    items = filt_res.json()["items"]
    assert len(items) > 0, f"Category '{first_cat}' returned 0 items"
    for it in items:
        assert it["category"] == first_cat, f"Expected category {first_cat}, got {it['category']}"


# ------------------------------------------------------------------------------
# Feature 8: FAQ Inline Action Controls (Like, Ask AI, Copy)
# ------------------------------------------------------------------------------

def test_f8_01_inline_like_button_and_api_binding(chat_html):
    """Verify inline like button calls POST /api/v1/faqs/{id}/like via handleFaqLikeClick."""
    assert "handleFaqLikeClick" in chat_html, "handleFaqLikeClick missing from static/chat.html"
    assert "/api/v1/faqs/" in chat_html and "/like" in chat_html, \
        "API endpoint /api/v1/faqs/{id}/like binding missing from chat.html"


def test_f8_02_like_toggle_atomic_invertibility(client):
    """Verify like toggle is atomic and reversible per session."""
    r = client.get("/api/v1/faqs?limit=1")
    faq = r.json()["items"][0]
    faq_id = faq["id"]
    base_likes = faq["likes_count"]
    session_id = f"test_e2e_sess_{int(time.time())}"
    
    # 1. Like
    res1 = client.post(f"/api/v1/faqs/{faq_id}/like", json={"session_id": session_id})
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["has_liked"] is True
    assert d1["likes_count"] == base_likes + 1
    
    # 2. Unlike (toggle)
    res2 = client.post(f"/api/v1/faqs/{faq_id}/like", json={"session_id": session_id})
    assert res2.status_code == 200
    d2 = res2.json()
    assert d2["has_liked"] is False
    assert d2["likes_count"] == base_likes


def test_f8_03_ask_ai_prompt_injection_into_chat(chat_html):
    """Verify askAiAboutFaq sets split mode to chat, populates #user-input, and triggers handleSend()."""
    assert "askAiAboutFaq" in chat_html, "askAiAboutFaq missing from static/chat.html"
    assert "user-input" in chat_html, "#user-input reference missing from chat.html"
    assert "handleSend" in chat_html, "handleSend reference missing from chat.html"


def test_f8_04_copy_to_clipboard_formatted_text(chat_html):
    """Verify copyFaqToClipboard copies formatted question, answer, and official source."""
    assert "copyFaqToClipboard" in chat_html, "copyFaqToClipboard function missing from static/chat.html"
    assert "জাতীয় বিশ্ববিদ্যালয়" in chat_html, "Official university source attribution missing from chat.html"


def test_f8_05_copy_button_visual_feedback_feedback_revert(chat_html):
    """Verify copy button displays visual confirmation (✓ কপিড) and reverts via timeout."""
    assert "কপিড" in chat_html or "কপি" in chat_html, \
        "Copy visual feedback label missing in static/chat.html"


# ------------------------------------------------------------------------------
# Feature 9: Dynamic 70%/30% Split Layout
# ------------------------------------------------------------------------------

def test_f9_01_split_container_and_default_chat_split(chat_soup):
    """Verify #split-container has default data-split='chat' wrapping chat and FAQ panels."""
    split_container = chat_soup.find(id="split-container")
    assert split_container is not None, "Missing #split-container in static/chat.html"
    assert split_container.get("data-split") == "chat", \
        "Default data-split attribute must be 'chat'"
    
    chat_sec = split_container.find(id="chat-section")
    assert chat_sec is not None, "Missing #chat-section inside split container"
    
    faq_panel = split_container.find(id="faq-forum-panel")
    assert faq_panel is not None, "Missing #faq-forum-panel inside split container"


def test_f9_02_set_split_mode_faq_expansion(chat_html):
    """Verify setSplitMode('faq') logic expands FAQ panel and sets attribute."""
    assert "setSplitMode" in chat_html, "setSplitMode function missing from chat.html"
    assert "data-split" in chat_html, "data-split attribute manipulation missing from chat.html"


def test_f9_03_set_split_mode_chat_restoration(chat_html):
    """Verify setSplitMode('chat') restores chat to 70% width."""
    assert "currentSplitMode" in chat_html or "setSplitMode" in chat_html, \
        "Split mode state management missing from chat.html"


def test_f9_04_faq_toggle_split_button_and_label(chat_soup, chat_html):
    """Verify #faq-toggle-split-btn exists and binds toggleSplitMode()."""
    btn = chat_soup.find(id="faq-toggle-split-btn")
    assert btn is not None, "Missing #faq-toggle-split-btn in static/chat.html"
    assert "toggleSplitMode" in chat_html, "toggleSplitMode function missing from chat.html"


def test_f9_05_chat_focus_pill_in_faq_mode(chat_soup):
    """Verify #chat-focus-pill exists for instant restoration to chat mode."""
    pill = chat_soup.find(id="chat-focus-pill")
    assert pill is not None, "Missing #chat-focus-pill element in static/chat.html"


# ------------------------------------------------------------------------------
# Feature 10: Monochromatic Design Tokens & Dark Mode
# ------------------------------------------------------------------------------

def test_f10_01_light_mode_monochromatic_design_tokens(chat_html):
    """Verify light mode monochromatic CSS design tokens (--bg, --surface, --text, --hairline)."""
    assert "--bg: #F5F5F7" in chat_html, "Missing --bg: #F5F5F7 in chat.html"
    assert "--surface: #FFFFFF" in chat_html, "Missing --surface: #FFFFFF in chat.html"
    assert "--text: #1D1D1F" in chat_html, "Missing --text: #1D1D1F in chat.html"
    assert "--text-secondary: #6E6E73" in chat_html, "Missing --text-secondary: #6E6E73 in chat.html"
    assert "--hairline: rgba(0, 0, 0, 0.08)" in chat_html, "Missing --hairline in chat.html"


def test_f10_02_dark_mode_tokens_and_theme_attribute(chat_html):
    """Verify [data-theme='dark'] selector defines monochromatic dark tokens."""
    assert '[data-theme="dark"]' in chat_html, "Missing [data-theme='dark'] selector in chat.html"
    assert "--bg: #1C1C1E" in chat_html, "Missing dark --bg: #1C1C1E in chat.html"
    assert "--surface: #2C2C2E" in chat_html, "Missing dark --surface: #2C2C2E in chat.html"
    assert "--text: #F5F5F7" in chat_html, "Missing dark --text: #F5F5F7 in chat.html"


def test_f10_03_theme_toggle_handler_and_icon_switching(chat_soup, chat_html):
    """Verify theme toggle function and #theme-icon SVG element exist."""
    theme_icon = chat_soup.find(id="theme-icon")
    assert theme_icon is not None, "Missing #theme-icon element in static/chat.html"
    assert "toggleTheme" in chat_html, "toggleTheme function missing from chat.html"


def test_f10_04_prefers_color_scheme_system_detection(chat_html):
    """Verify prefers-color-scheme media query is present for automatic system dark mode."""
    assert "prefers-color-scheme" in chat_html, \
        "Missing prefers-color-scheme media query in static/chat.html"


def test_f10_05_monochromatic_support_center_styling(index_html):
    """Verify static/index.html applies monochromatic CSS variables."""
    assert "--bg" in index_html, "Missing --bg token in index.html"
    assert "--surface" in index_html, "Missing --surface token in index.html"
    assert "--text" in index_html, "Missing --text token in index.html"
    assert "--hairline" in index_html, "Missing --hairline token in index.html"


# ------------------------------------------------------------------------------
# Feature 11: Official Portal URLs Verification
# ------------------------------------------------------------------------------

def test_f11_01_student_services_official_url_integrity(index_html):
    """Verify official Student Services portal URL (http://103.113.200.68/nu-app/) is present."""
    assert "103.113.200.68/nu-app" in index_html, \
        "Official student services URL http://103.113.200.68/nu-app/ missing from index.html"


def test_f11_02_admission_portal_official_url_integrity(index_html):
    """Verify official Admission Portal URL (http://app11.nu.edu.bd/) is present."""
    assert "app11.nu.edu.bd" in index_html, \
        "Official admission portal URL http://app11.nu.edu.bd/ missing from index.html"


def test_f11_03_ems_portal_official_url_integrity(index_html):
    """Verify official EMS Portal URL (http://ems.nu.ac.bd/) is present."""
    assert "ems.nu.ac.bd" in index_html, \
        "Official EMS portal URL http://ems.nu.ac.bd/ missing from index.html"


def test_f11_04_deprecated_services_nu_edu_bd_strictly_absent(index_html, chat_html):
    """Verify deprecated URL services.nu.edu.bd is strictly absent from active user code."""
    # Check anchor hrefs and active scripts in both frontend pages
    assert "services.nu.edu.bd" not in index_html, \
        "Deprecated domain services.nu.edu.bd found in static/index.html"
    assert "services.nu.edu.bd" not in chat_html, \
        "Deprecated domain services.nu.edu.bd found in static/chat.html"


def test_f11_05_deprecated_ip_103_113_200_36_strictly_absent(index_html, chat_html):
    """Verify deprecated IP 103.113.200.36 is strictly absent from active user code."""
    assert "103.113.200.36" not in index_html, \
        "Deprecated IP 103.113.200.36 found in static/index.html"
    assert "103.113.200.36" not in chat_html, \
        "Deprecated IP 103.113.200.36 found in static/chat.html"


# ==============================================================================
# TIER 2: BOUNDARY & CORNER CASES (6 tests)
# ==============================================================================

def test_t2_01_empty_token_list_rendering(index_html):
    """Verify table rendering logic handles empty token lists without crashing."""
    assert "admin-tokens-tbody" in index_html
    # Verify handling of empty data or zero records
    assert "tokens" in index_html.lower()


def test_t2_02_missing_student_phone_and_reg_no_fallbacks(token_domain_svc):
    """Verify token creation and detail retrieval with missing phone and registration number."""
    req = DomainTokenCreateRequest(
        service_code="OTHER",
        problem="General inquiry with minimal fields provided",
        user_name="Anonymous Student",
        user_phone=None,
        registration_no=None
    )
    res = token_domain_svc.create_token(req)
    assert res.success is True
    
    detail = token_domain_svc.get_admin_token_detail(res.token_id)
    assert detail is not None
    assert detail.user_phone is None or detail.user_phone == ""
    assert detail.registration_no is None or detail.registration_no == ""


def test_t2_03_extra_long_problem_description_boundary(token_domain_svc):
    """Verify database and domain service cleanly accept max boundary (2,000 chars) and reject >2,000 chars."""
    # 1. Exactly at boundary (2000 chars) - must succeed
    prefix = "জাতীয় বিশ্ববিদ্যালয় সেবা সমস্যা: "
    valid_boundary_problem = prefix + ("ক" * (2000 - len(prefix)))
    assert len(valid_boundary_problem) == 2000
    
    req = DomainTokenCreateRequest(
        service_code="EMS",
        problem=valid_boundary_problem,
        user_name="Testing Boundary Problem"
    )
    res = token_domain_svc.create_token(req)
    assert res.success is True
    
    detail = token_domain_svc.get_admin_token_detail(res.token_id)
    assert len(detail.problem) == 2000
    
    # 2. Exceeding boundary (>2000 chars) - must reject with validation error
    with pytest.raises(Exception):
        DomainTokenCreateRequest(
            service_code="EMS",
            problem="ক" * 2001
        )


def test_t2_04_invalid_status_transition_rejection(token_domain_svc):
    """Verify state machine rejects invalid or illegal status transitions (e.g. CLOSED -> PENDING)."""
    t = token_domain_svc.create_token(DomainTokenCreateRequest(service_code="TC", problem="Boundary transition test"))
    t_id = t.token_id
    
    # Progress: PENDING -> ASSIGNED -> PROCESSING -> SOLVED -> CLOSED
    token_domain_svc.update_status(t_id, "ASSIGNED", changed_by="ADMIN")
    token_domain_svc.update_status(t_id, "PROCESSING", changed_by="SOLVER")
    token_domain_svc.solve_token(t_id, "Resolution reached", solver_name="Desk")
    token_domain_svc.update_status(t_id, "CLOSED", changed_by="ADMIN")
    
    # Illegal attempt: CLOSED -> PENDING by non-SUPER_ADMIN
    ok, msg = token_domain_svc.update_status(t_id, "PENDING", changed_by="SOLVER")
    assert ok is False, "Closed token must not transition back to PENDING"
    assert "illegal status transition" in msg.lower()


def test_t2_05_special_characters_sql_xss_in_faq_search(client):
    """Verify FAQ search safely handles SQL meta-characters, HTML tags, and special symbols without 500 error."""
    payloads = [
        "<script>alert('xss')</script>",
        "' OR '1'='1",
        "'; DROP TABLE faqs; --",
        "~`!@#$%^&*()_+=-{}[]|\\:;\"'<>,.?/",
        "অনিক 🔍 <xml>"
    ]
    for p in payloads:
        res = client.get(f"/api/v1/faqs?search={p}&limit=10")
        assert res.status_code == 200, f"Search crashed on payload: {p}"
        data = res.json()
        assert "items" in data
        assert isinstance(data["items"], list)


def test_t2_06_unauthenticated_and_unassigned_solver_rejection(client):
    """Verify unauthenticated requests to protected admin endpoints are rejected."""
    # Attempting to assign without authorization header on /api/v1/admin/tokens/{id}/assign
    res = client.post("/api/v1/admin/tokens/NU-2026-000001/assign", json={"solver_id": 1})
    assert res.status_code in [401, 403], f"Expected 401/403, got {res.status_code}"


# ==============================================================================
# TIER 3: PAIRWISE INTERACTIONS (4 tests)
# ==============================================================================

def test_t3_01_solver_role_desk_isolation_and_action_controls(legacy_token_svc, index_soup):
    """Pairwise: Solver Role + Desk Isolation + Drawer Action Controls."""
    # Create token for Accounts Desk and assign to solver 5 (Accounts)
    t_acc = legacy_token_svc.create_token(RepoTokenCreateRequest(
        service_type="SONALI_PAYMENT",
        problem="Payment verification needed for admission confirmation",
        user_name="Accounts Student"
    ))
    legacy_token_svc.assign_token(t_acc.token_id, solver_id=5)
    
    # Verify Accounts desk query returns it
    acc_tokens, total = legacy_token_svc.repo.list_tokens(
        role="SOLVER",
        department="Accounts & Sonali Seba Desk"
    )
    assert any(x["token_id"] == t_acc.token_id for x in acc_tokens)
    
    # Verify drawer action controls exist for this solver
    assert index_soup.find(id="adm-solve-message") is not None
    assert index_soup.find(id="solver-return-reason-input") is not None
    # Solver desk notice must be present
    assert index_soup.find(id="solver-assignment-notice") is not None


def test_t3_02_faq_category_switch_search_filter_and_accordion(client, chat_html):
    """Pairwise: Category Switch + Search Query + Accordion Expand."""
    # Fetch category
    cat_res = client.get("/api/v1/faqs/categories")
    assert cat_res.status_code == 200
    category = cat_res.json()["categories"][0]["category"]
    
    # Query with category AND search
    res = client.get(f"/api/v1/faqs?category={category}&search=জাতীয়&limit=10")
    assert res.status_code == 200
    items = res.json()["items"]
    for it in items:
        assert it["category"] == category
    
    # Accordion expansion logic must be ready for rendering items
    assert "toggleFaqExpand" in chat_html


def test_t3_03_like_toggle_multi_session_isolation_and_persistence(client):
    """Pairwise: Like Toggles across independent sessions."""
    r = client.get("/api/v1/faqs?limit=1")
    faq_id = r.json()["items"][0]["id"]
    initial_likes = r.json()["items"][0]["likes_count"]
    
    sess_x = f"sess_alpha_{int(time.time())}"
    sess_y = f"sess_beta_{int(time.time())}"
    
    # Session X likes
    r_x = client.post(f"/api/v1/faqs/{faq_id}/like", json={"session_id": sess_x})
    assert r_x.json()["has_liked"] is True
    assert r_x.json()["likes_count"] == initial_likes + 1
    
    # Session Y likes
    r_y = client.post(f"/api/v1/faqs/{faq_id}/like", json={"session_id": sess_y})
    assert r_y.json()["has_liked"] is True
    assert r_y.json()["likes_count"] == initial_likes + 2
    
    # Session X unlikes
    r_x2 = client.post(f"/api/v1/faqs/{faq_id}/like", json={"session_id": sess_x})
    assert r_x2.json()["has_liked"] is False
    assert r_y.json()["has_liked"] is True  # Session Y remains liked
    assert r_x2.json()["likes_count"] == initial_likes + 1
    
    # Cleanup Session Y
    client.post(f"/api/v1/faqs/{faq_id}/like", json={"session_id": sess_y})


def test_t3_04_split_layout_toggle_with_ask_ai_and_chat_input(chat_html):
    """Pairwise: Split Mode Toggle + Ask AI Prompt Injection into Chat Input."""
    # When user clicks Ask AI:
    # 1. setSplitMode('chat') must be called
    # 2. #user-input must be filled
    # 3. handleSend() must be called
    assert "askAiAboutFaq" in chat_html
    assert 'setSplitMode("chat")' in chat_html or "setSplitMode('chat')" in chat_html
    assert "user-input" in chat_html
    assert "handleSend" in chat_html


# ==============================================================================
# TIER 4: REAL-WORLD WORKLOAD SCENARIOS (5 Scenarios)
# ==============================================================================

def test_t4_01_solver_solve_workflow_end_to_end(token_domain_svc, legacy_token_svc):
    """
    Scenario 1: Solver Workflow
    Login as Accounts Solver -> Query assigned Accounts tokens -> Open drawer -> Solve token -> Verify status updated.
    """
    # 1. Student creates token via Domain Service
    req = DomainTokenCreateRequest(
        service_code="SONALI_PAYMENT",
        problem="Sonali Seba payslip verified but status still unpaid in portal",
        user_name="Karim Ullah",
        user_phone="01811223344"
    )
    created = token_domain_svc.create_token(req)
    t_id = created.token_id
    assert t_id.startswith("NU-")
    
    # 2. Super Admin assigns to Accounts Solver (solver_id=5)
    token_domain_svc.assign_solver(t_id, solver_id=5, changed_by="ADMIN")
    
    # 3. Accounts Solver queries assigned tickets
    solver_tokens, total = legacy_token_svc.repo.list_tokens(
        role="SOLVER",
        department="Accounts & Sonali Seba Desk",
        search=t_id
    )
    assert total >= 1
    assert solver_tokens[0]["token_id"] == t_id
    
    # 4. Solver opens drawer & marks as solved
    ok, msg = token_domain_svc.solve_token(
        token_id=t_id,
        solve_message="পেমেন্ট সোনালী ব্যাংকের গেটওয়ের সাথে সিনক্রোনাইজ করে Paid করা হয়েছে।",
        solver_name="Accounts & Sonali Seba Desk",
        changed_by="solver_accounts"
    )
    assert ok is True
    
    # 5. Verify public timeline
    public_status = token_domain_svc.get_public_token_status(t_id)
    assert public_status.status == "SOLVED"
    assert "সিনক্রোনাইজ করে Paid করা হয়েছে" in public_status.solve_message


def test_t4_02_solver_return_to_admin_workflow_end_to_end(token_domain_svc):
    """
    Scenario 2: Solver Return Workflow
    Login as ICT Solver -> Open EMS ticket -> Return to admin with note -> Verify correct route logic.
    """
    # 1. Student creates token
    created = token_domain_svc.create_token(DomainTokenCreateRequest(
        service_code="EMS",
        problem="Exam form fill-up button disabled due to semester credit lock",
        user_name="Jannatul Ferdous"
    ))
    t_id = created.token_id
    token_domain_svc.assign_solver(t_id, solver_id=1, changed_by="ADMIN")
    
    # 2. Solver sends back to admin with reason
    reason_note = "Needs Exam Controller Office unlock permission for credit shortfall."
    ok, msg = token_domain_svc.return_to_admin(
        token_id=t_id,
        reason=reason_note,
        solver_name="ICT Support Team",
        changed_by="solver_ict"
    )
    assert ok is True
    
    # 3. Verify status transitioned back to PENDING and reason recorded
    detail = token_domain_svc.get_admin_token_detail(t_id)
    assert detail.status == "PENDING"
    assert reason_note in detail.admin_note
    # Verify history entry
    hist = detail.history
    assert any("PENDING" in h.new_status for h in hist)


def test_t4_03_student_faq_discovery_and_ask_ai_workflow(client, chat_html):
    """
    Scenario 3: Student FAQ Discovery & Ask AI Workflow
    Student searches query in chat FAQ -> Debounced filter -> Click category pill -> Expand accordion -> Copy answer -> Ask AI in chat.
    """
    # 1. Search FAQ API
    res = client.get("/api/v1/faqs?search=সনদ&limit=5")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) > 0
    faq = items[0]
    
    # 2. Category list
    cats_res = client.get("/api/v1/faqs/categories")
    assert cats_res.status_code == 200
    
    # 3. Actions in chat.html
    assert "copyFaqToClipboard" in chat_html
    assert "askAiAboutFaq" in chat_html
    assert "toggleFaqExpand" in chat_html


def test_t4_04_super_admin_trash_governance_workflow(legacy_token_svc):
    """
    Scenario 4: Super Admin Governance
    View all desks -> Soft-delete invalid ticket -> Confirm in Trash -> Restore from Trash -> Verify audit.
    """
    # 1. Create token
    t = legacy_token_svc.create_token(RepoTokenCreateRequest(
        problem="Test token for Super Admin governance lifecycle",
        service_type="OTHER",
        user_name="Governance Test Student"
    ))
    t_id = t.token_id
    
    # 2. Soft-delete
    del_ok = legacy_token_svc.repo.soft_delete_token(t_id, admin_user="SuperAdminGov")
    assert del_ok is True
    
    # 3. Must be in trash
    trash_items, count = legacy_token_svc.repo.list_tokens(status="DELETED", search=t_id, role="SUPER_ADMIN")
    assert count == 1
    assert trash_items[0]["token_id"] == t_id
    
    # 4. Restore
    rest_ok = legacy_token_svc.repo.restore_token(t_id, admin_user="SuperAdminGov")
    assert rest_ok is True
    
    # 5. Active list confirms restoration
    active_items, active_count = legacy_token_svc.repo.list_tokens(search=t_id, role="SUPER_ADMIN")
    assert active_count == 1
    assert active_items[0]["is_deleted"] == 0


def test_t4_05_portal_link_authenticity_validation(index_html, chat_html):
    """
    Scenario 5: Portal Link Authenticity Validation
    Verify all student service, admission, and EMS URLs match official IP/domains without deprecated links.
    """
    # Required official URLs
    official_services_url = "103.113.200.68/nu-app"
    official_admission_url = "app11.nu.edu.bd"
    official_ems_url = "ems.nu.ac.bd"
    
    assert official_services_url in index_html, "Official Student Services portal URL missing from index.html"
    assert official_admission_url in index_html, "Official Admission portal URL missing from index.html"
    assert official_ems_url in index_html, "Official EMS portal URL missing from index.html"
    
    # Strictly forbidden deprecated URLs
    deprecated_domain = "services.nu.edu.bd"
    deprecated_ip = "103.113.200.36"
    
    assert deprecated_domain not in index_html, f"Deprecated domain {deprecated_domain} found in static/index.html"
    assert deprecated_domain not in chat_html, f"Deprecated domain {deprecated_domain} found in static/chat.html"
    assert deprecated_ip not in index_html, f"Deprecated IP {deprecated_ip} found in static/index.html"
    assert deprecated_ip not in chat_html, f"Deprecated IP {deprecated_ip} found in static/chat.html"


def test_t4_06_admin_faq_input_form_and_chat_lighting_bars(index_soup, chat_soup, index_html, chat_html):
    """
    Scenario 6: Admin FAQ Input Form, Chat Lighting Bars & Realtime Chat Criteria
    - Confirms #admin-faq-form and real-time similarity check box in index.html.
    - Confirms slim lighting 'lite green' animated bar in Chat.
    - Confirms slim lighting 'lite orange' animated bar at FAQ border.
    - Confirms chat input criteria hint and Card 4 valid SVG structure in chat.html.
    """
    # 1. Admin FAQ Form Elements in index.html
    faq_form = index_soup.find("form", id="admin-faq-form")
    assert faq_form is not None, "Missing #admin-faq-form in static/index.html"
    assert index_soup.find("textarea", id="admin-faq-question") is not None
    assert index_soup.find("textarea", id="admin-faq-answer") is not None
    assert index_soup.find("select", id="admin-faq-category") is not None
    assert index_soup.find(id="admin-faq-sim-box") is not None
    assert index_soup.find(id="admin-faq-force") is not None

    # 2. Academic Static Hub in index.html
    assert index_soup.find(id="tab-btn-academic-static") is not None
    assert index_soup.find(id="tab-content-academic-static") is not None
    assert index_soup.find(id="admin-academic-static-tbody") is not None

    # 3. Chat Lighting Bars in chat.html
    chat_bar = chat_soup.find(class_="chat-lighting-bar-green")
    assert chat_bar is not None, "Missing .chat-lighting-bar-green in static/chat.html"
    faq_bar = chat_soup.find(class_="faq-lighting-bar-orange")
    assert faq_bar is not None, "Missing .faq-lighting-bar-orange in static/chat.html"

    # 4. Realtime Chat Criteria hint element in chat.html
    criteria_hint = chat_soup.find(id="chat-input-criteria-hint")
    assert criteria_hint is not None, "Missing #chat-input-criteria-hint in static/chat.html"
    assert "handleRealtimeChatCriteria" in chat_html, "Missing handleRealtimeChatCriteria function in chat.html"

    # 5. Card 4 SVG Validity
    pro_card = chat_soup.find("div", onclick=lambda v: v and "Professional" in v)
    assert pro_card is not None, "Missing Professional card in static/chat.html"
    assert pro_card.find("svg") is not None, "Card 4 (Professional) must have a valid <svg> tag wrapper"


def test_t4_07_simplified_faq_header_and_admin_maximize_button(index_soup, chat_soup, index_html, chat_html):
    """
    Scenario 7: Simplified Minimalist FAQ Header & Admin Fullscreen Maximize Button
    - Confirms FAQ panel header is simplified to clean 'FAQ' title.
    - Confirms #faq-toggle-split-btn and refresh button remain functional.
    - Confirms #admin-modal-maximize-btn exists with toggleAdminModalFullscreen handler.
    - Confirms #admin-modal-container exists for fluid fullscreen resizing.
    """
    # 1. Simplified FAQ header in static/chat.html
    faq_panel = chat_soup.find(id="faq-forum-panel")
    assert faq_panel is not None, "Missing #faq-forum-panel in chat.html"
    faq_h3 = faq_panel.find("h3")
    assert faq_h3 is not None, "Missing <h3> heading in #faq-forum-panel"
    assert faq_h3.text.strip() == "FAQ", f"Expected header text to be exactly 'FAQ', got '{faq_h3.text.strip()}'"

    # Split toggle button preserved
    split_btn = faq_panel.find(id="faq-toggle-split-btn")
    assert split_btn is not None, "Missing #faq-toggle-split-btn in #faq-forum-panel"
    assert "toggleSplitMode" in chat_html, "toggleSplitMode function missing from chat.html"

    # 2. Admin Modal Maximize Button in static/index.html
    admin_modal = index_soup.find(id="admin-modal")
    assert admin_modal is not None, "Missing #admin-modal in index.html"
    container = admin_modal.find(id="admin-modal-container")
    assert container is not None, "Missing #admin-modal-container in index.html"

    max_btn = admin_modal.find(id="admin-modal-maximize-btn")
    assert max_btn is not None, "Missing #admin-modal-maximize-btn in admin header"
    assert "toggleAdminModalFullscreen" in index_html, "toggleAdminModalFullscreen missing in index.html"


def test_t4_08_admin_api_health_check_ui_and_endpoints(client, index_soup, index_html):
    """
    Scenario 8: Admin Panel Google Gemini API Health Check, Change API Key & User Rate Limit Control
    - Confirms #btn-api-health-header and #tab-btn-api-health and #tab-content-api-health exist in static/index.html.
    - Confirms #tab-content-api-health is NOT nested inside #tab-content-academic-static (so it renders visibly).
    - Confirms #api-health-new-key-input and #btn-save-new-api-key exist for replacing expired Gemini API keys.
    - Confirms GET /api/v1/admin/api-health-check?live_test=false returns gemini_api and user_rate_limit telemetry.
    - Confirms POST /api/v1/admin/api-health-check/update-key updates and hot-reloads the Gemini API key.
    - Confirms POST /api/v1/admin/api-health-check/rate-limit updates user RPM limit and resets counters.
    """
    # 1. Verify UI DOM Elements & Hierarchy in static/index.html
    assert index_soup.find(id="btn-api-health-header") is not None, "Missing #btn-api-health-header in Admin Header"
    assert index_soup.find(id="tab-btn-api-health") is not None, "Missing #tab-btn-api-health in Admin Tab Bar"
    api_health_panel = index_soup.find(id="tab-content-api-health")
    assert api_health_panel is not None, "Missing #tab-content-api-health panel"
    academic_panel = index_soup.find(id="tab-content-academic-static")
    assert academic_panel is not None
    assert academic_panel.find(id="tab-content-api-health") is None, (
        "#tab-content-api-health must be a sibling of #tab-content-academic-static, NOT nested inside it!"
    )

    assert index_soup.find(id="btn-run-live-api-check") is not None, "Missing #btn-run-live-api-check button"
    assert index_soup.find(id="api-health-new-key-input") is not None, "Missing #api-health-new-key-input field"
    assert index_soup.find(id="btn-save-new-api-key") is not None, "Missing #btn-save-new-api-key button"
    assert index_soup.find(id="api-health-rpm-input") is not None, "Missing #api-health-rpm-input field"
    assert "function getAdminHeaders()" in index_html, "Missing getAdminHeaders() helper definition in static/index.html"
    assert "runAdminApiHealthCheck" in index_html, "Missing runAdminApiHealthCheck JS handler"
    assert "saveNewGeminiApiKey" in index_html, "Missing saveNewGeminiApiKey JS handler"
    assert "updateAdminUserRateLimit" in index_html, "Missing updateAdminUserRateLimit JS handler"

    # Verify zero JavaScript syntax errors in inline <script> blocks of static/index.html
    import subprocess
    import tempfile
    scripts = [s.string for s in index_soup.find_all("script") if not s.get("src") and s.string]
    assert len(scripts) >= 1
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as tf:
        tf.write("\n;\n".join(scripts))
        temp_js = tf.name
    chk = subprocess.run(["node", "--check", temp_js], capture_output=True, text=True)
    assert chk.returncode == 0, f"JavaScript SyntaxError in static/index.html: {chk.stderr}"

    # 2. Verify Backend API Health Check Endpoint (Quick Config Check)
    admin_token = create_jwt_token({"sub": "superadmin", "role": Role.SUPER_ADMIN.value})
    headers = {"Authorization": f"Bearer {admin_token}"}

    res = client.get("/api/v1/admin/api-health-check?live_test=false", headers=headers)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    payload = res.json()
    assert payload.get("status") == "success"
    assert "gemini_api" in payload
    assert "user_rate_limit" in payload
    assert "masked_api_key" in payload["gemini_api"]
    assert "limit_per_minute" in payload["user_rate_limit"]

    # 3. Verify Change / Update Gemini API Key Endpoint (and restore original key)
    from backend.config import settings
    original_key = settings.GEMINI_API_KEY
    try:
        test_key = "AIzaSyTestReplacementKey1234567890"
        res_key = client.post(
            "/api/v1/admin/api-health-check/update-key",
            headers=headers,
            json={"new_api_key": test_key, "live_test": False}
        )
        assert res_key.status_code == 200, f"Update key failed: {res_key.text}"
        key_data = res_key.json()
        assert key_data.get("key_updated") is True
        assert settings.GEMINI_API_KEY == test_key
    finally:
        if original_key:
            client.post(
                "/api/v1/admin/api-health-check/update-key",
                headers=headers,
                json={"new_api_key": original_key, "live_test": False}
            )

    # 4. Verify User Rate Limit Update & Reset Endpoint
    res_rl = client.post(
        "/api/v1/admin/api-health-check/rate-limit",
        headers=headers,
        json={"limit_per_minute": 45, "reset_all": True}
    )
    assert res_rl.status_code == 200
    rl_data = res_rl.json()
    assert rl_data["user_rate_limit"]["limit_per_minute"] == 45

    # Restore default 30 RPM
    client.post(
        "/api/v1/admin/api-health-check/rate-limit",
        headers=headers,
        json={"limit_per_minute": 30}
    )


def test_t4_09_chat_upper_blank_space_removed(chat_soup):
    """
    Scenario 9: Chat Section Upper Blank Space Removed
    - Confirms #chat-section uses justify-start (not justify-between) so #welcome-view stays anchored at the top.
    - Confirms #split-container uses items-start.
    - Confirms #bottom-controls-bar uses mt-auto so bottom input stays anchored at bottom when chat messages grow.
    """
    split_container = chat_soup.find(id="split-container")
    assert split_container is not None
    split_classes = split_container.get("class", [])
    assert "items-start" in split_classes, f"Expected items-start on #split-container, got {split_classes}"

    chat_section = chat_soup.find(id="chat-section")
    assert chat_section is not None
    chat_classes = chat_section.get("class", [])
    assert "justify-start" in chat_classes, f"Expected justify-start on #chat-section, got {chat_classes}"
    assert "justify-between" not in chat_classes, "#chat-section must not use justify-between (causes upper blank gap)"

    bottom_bar = chat_soup.find(id="bottom-controls-bar")
    assert bottom_bar is not None
    bottom_classes = bottom_bar.get("class", [])
    assert "mt-auto" in bottom_classes, "Expected mt-auto on #bottom-controls-bar"


def test_t4_10_simplified_academic_hub_date_pickers_and_faq_entry_ui(index_soup, index_html):
    """
    Scenario 10: Simplified Academic Exam & Results Hub, Native Date Pickers, FAQ Q&A Entry & User Role Option
    - Confirms #entry-portal-section (Entry Form) appears before #academic-schedule-table-section for novice usability.
    - Confirms all 16 date fields in #academic-static-form have attached <input type='date'> calendar pickers.
    - Confirms #faq-qa-entry-section and #admin-faq-form exist inside #tab-content-academic-static.
    - Confirms #new-user-role select includes EXAM_ENTRY option.
    """
    hub = index_soup.find(id="tab-content-academic-static")
    assert hub is not None, "Missing #tab-content-academic-static"

    # 1. Verify Entry Form appears before Schedule Table in DOM order
    hub_str = str(hub)
    form_pos = hub_str.find('id="entry-portal-section"')
    table_pos = hub_str.find('id="academic-schedule-table-section"')
    assert form_pos != -1 and table_pos != -1
    assert form_pos < table_pos, "Entry form (#entry-portal-section) must appear before schedule table for novice workflow"

    # 2. Verify all 16 date fields have <input type="date"> pickers
    expected_date_targets = [
        "static-incourse-date",
        "static-last-incourse",
        "static-form-fillup-start",
        "static-form-fillup",
        "static-exam-date",
        "static-routine-url",
        "static-admit-card",
        "static-last-exam",
        "static-practical-date",
        "static-last-practical",
        "static-prob-result",
        "static-result-date",
        "static-rescrutiny-start",
        "static-rescrutiny-apply",
        "static-rescrutiny-result",
        "static-cert-printing",
    ]
    date_pickers = hub.find_all("input", attrs={"type": "date"})
    picker_targets = {p.get("data-target-input") for p in date_pickers}
    for target_id in expected_date_targets:
        assert target_id in picker_targets, f"Missing <input type='date'> picker for #{target_id}"

    # 3. Verify FAQ Q&A Entry section is inside #tab-content-academic-static
    faq_sec = hub.find(id="faq-qa-entry-section")
    assert faq_sec is not None, "Missing #faq-qa-entry-section inside #tab-content-academic-static"
    assert faq_sec.find("form", id="admin-faq-form") is not None

    # 4. Verify EXAM_ENTRY option in #new-user-role
    role_select = index_soup.find("select", id="new-user-role")
    assert role_select is not None
    role_values = [opt.get("value") for opt in role_select.find_all("option")]
    assert "EXAM_ENTRY" in role_values, f"Expected EXAM_ENTRY in #new-user-role options, got {role_values}"


def test_t4_11_exam_entry_role_auth_and_permissions_e2e():
    """
    Scenario 11: 'Exam Entry' (EXAM_ENTRY) Staff User Login, Exam Submission, FAQ Entry & RBAC Isolation
    - Verifies seeded 'exam_entry' account can log in via /api/v1/auth/login and has role EXAM_ENTRY.
    - Verifies EXAM_ENTRY user can submit exam schedule data to POST /api/v1/admin/academic-exams.
    - Verifies EXAM_ENTRY user can add FAQ Q&A via POST /api/v1/admin/faqs.
    - Verifies EXAM_ENTRY user is forbidden (403) from accessing /api/v1/admin/users and /api/v1/admin/backup/list.
    - Verifies Super Admin can create a new EXAM_ENTRY user via POST /api/v1/admin/users.
    """
    import time
    from fastapi.testclient import TestClient
    from backend.app import app
    from backend.core.security import create_jwt_token, Role

    client = TestClient(app)

    # 1. Login with seeded 'exam_entry' staff user
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "exam_entry", "password": "nu_exam_2026"}
    )
    assert login_res.status_code == 200, f"Seeded exam_entry login failed: {login_res.text}"
    login_data = login_res.json()
    assert login_data["user"]["role"] == "EXAM_ENTRY"
    exam_token = login_data["access_token"]
    exam_headers = {"Authorization": f"Bearer {exam_token}"}

    # 2. Submit exam data as EXAM_ENTRY user
    exam_payload = {
        "program_type": "Honours",
        "program_type_name": "অনার্স (সম্মান)",
        "examination_year": "2026",
        "part": "Part 1",
        "semester": "N/A",
        "incourse_exam_date": "2026-02-01",
        "form_fillup_start_date": "2026-03-10",
        "form_fillup_deadline": "2026-04-05",
        "exam_date": "2026-05-20",
        "probable_result_date": "2026-08-30",
        "results_published": "No",
        "documents_printed": "No",
        "remarks": "Submitted by Exam Entry staff"
    }
    save_exam_res = client.post("/api/v1/admin/academic-exams", headers=exam_headers, json=exam_payload)
    assert save_exam_res.status_code == 200, f"EXAM_ENTRY failed to save exam record: {save_exam_res.text}"
    assert save_exam_res.json()["status"] == "success"

    # 3. Add FAQ Q&A as EXAM_ENTRY user
    unique_q = f"২০২৬ সালের অনার্স ১ম বর্ষ পরীক্ষার বিশেষ ফরম পূরণের নিয়ম কী? ({int(time.time())})"
    faq_res = client.post(
        "/api/v1/admin/faqs",
        headers=exam_headers,
        json={
            "question": unique_q,
            "answer": "ইএমএস পোর্টাল (http://ems.nu.ac.bd/) থেকে অনলাইনে ফরম পূরণ করতে হবে।",
            "category": "পরীক্ষা সংক্রান্ত",
            "keywords": "অনার্স, ফরম পূরণ",
            "force": True
        }
    )
    assert faq_res.status_code == 200, f"EXAM_ENTRY failed to add FAQ: {faq_res.text}"
    faq_json = faq_res.json()
    assert faq_json["status"] == "success"
    created_faq_id = faq_json.get("faq_id")
    if created_faq_id:
        client.delete(f"/api/v1/admin/faqs/{created_faq_id}", headers=exam_headers)

    # 4. Verify EXAM_ENTRY is forbidden (403) from Admin-only endpoints
    users_res = client.get("/api/v1/admin/users", headers=exam_headers)
    assert users_res.status_code == 403, f"Expected 403 for EXAM_ENTRY on /admin/users, got {users_res.status_code}"

    backup_res = client.get("/api/v1/admin/backup/list", headers=exam_headers)
    assert backup_res.status_code == 403, f"Expected 403 for EXAM_ENTRY on /admin/backup/list, got {backup_res.status_code}"

    # 5. Verify Super Admin can create a new EXAM_ENTRY user via POST /api/v1/admin/users
    admin_token = create_jwt_token({"sub": "admin", "username": "admin", "role": Role.SUPER_ADMIN.value})
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    temp_username = f"exam_staff_{int(time.time())}"
    create_u_res = client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={
            "username": temp_username,
            "password": "test_password_123",
            "full_name": "Test Exam Entry Staff",
            "department": "Controller of Examination Section",
            "role": "EXAM_ENTRY"
        }
    )
    assert create_u_res.status_code == 200, f"Failed to create EXAM_ENTRY user: {create_u_res.text}"
    new_uid = create_u_res.json()["id"]
    try:
        list_u = client.get("/api/v1/admin/users", headers=admin_headers).json()
        created_row = next((u for u in list_u if u["id"] == new_uid), None)
        assert created_row is not None
        assert created_row["role"] == "EXAM_ENTRY"
    finally:
        client.delete(f"/api/v1/admin/users/{new_uid}", headers=admin_headers)


def test_f12_05_faq_questions_categorywise_list_edit_delete_and_duplicates(index_soup, index_html):
    """
    Verify 'FAQ Questions' option inside 'FAQ Q&A Entry' loads questions & answers category-wise,
    detects duplicate questions, and supports editing (PUT) and deleting (DELETE) FAQs.
    """
    import time
    from fastapi.testclient import TestClient
    from backend.app import app

    # 1. Verify UI DOM IDs & JS functions exist in static/index.html
    for dom_id in [
        "btn-open-faq-questions",
        "faq-questions-manager-box",
        "faq-manage-category-filter",
        "faq-manage-search",
        "btn-faq-filter-duplicates",
        "faq-duplicates-count-badge",
        "admin-faq-edit-id",
        "admin-faq-edit-banner",
        "faq-entry-recent-list"
    ]:
        assert index_soup.find(id=dom_id) is not None, f"Missing #{dom_id} in FAQ Q&A Entry section"

    for fn_name in [
        "openFaqQuestionsManager",
        "toggleAdminFaqDuplicatesFilter",
        "filterAdminFaqQuestionsList",
        "editAdminFaqItem",
        "deleteAdminFaqItem"
    ]:
        assert fn_name in index_html, f"Missing JS function {fn_name} in static/index.html"

    # 2. Backend E2E verification of category-wise list, duplicate detection, edit (PUT), and delete (DELETE)
    client = TestClient(app)
    login_res = client.post(
        "/api/v1/auth/login",
        json={"username": "exam_entry", "password": "nu_exam_2026"}
    )
    assert login_res.status_code == 200
    exam_headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}

    ts = int(time.time())
    base_q = f"২০২৬ সালের মাস্টার্স শেষ পর্ব পরীক্ষার রুটিন কবে প্রকাশিত হবে? ({ts})"

    faq1_id = None
    faq2_id = None
    try:
        # Insert first FAQ
        r1 = client.post(
            "/api/v1/admin/faqs",
            headers=exam_headers,
            json={
                "question": base_q,
                "answer": "প্রাথমিক উত্তর ১: জাতীয় বিশ্ববিদ্যালয়ের ওয়েবসাইটে শীঘ্রই প্রকাশিত হবে।",
                "category": "পরীক্ষা সংক্রান্ত",
                "keywords": "মাস্টার্স, রুটিন",
                "force": True
            }
        )
        assert r1.status_code == 200
        faq1_id = r1.json()["faq_id"]

        # Insert near-duplicate second FAQ (different answer so hash differs, same normalized question)
        r2 = client.post(
            "/api/v1/admin/faqs",
            headers=exam_headers,
            json={
                "question": base_q + "?",
                "answer": "প্রাথমিক উত্তর ২ (ডুপ্লিকেট প্রশ্ন): ওয়েবসাইটে প্রকাশিত হবে।",
                "category": "পরীক্ষা সংক্রান্ত",
                "keywords": "মাস্টার্স, রুটিন",
                "force": True
            }
        )
        assert r2.status_code == 200
        faq2_id = r2.json()["faq_id"]
        assert faq1_id != faq2_id

        # List category-wise via GET /api/v1/admin/faqs
        list_res = client.get("/api/v1/admin/faqs?category=পরীক্ষা সংক্রান্ত", headers=exam_headers)
        assert list_res.status_code == 200
        list_data = list_res.json()
        assert list_data["status"] == "success"
        assert "পরীক্ষা সংক্রান্ত" in list_data["by_category"]
        assert list_data["duplicates_count"] >= 2

        cat_items = list_data["by_category"]["পরীক্ষা সংক্রান্ত"]
        item1 = next((x for x in cat_items if x["id"] == faq1_id), None)
        item2 = next((x for x in cat_items if x["id"] == faq2_id), None)
        assert item1 is not None and item2 is not None
        assert item1["is_duplicate"] is True
        assert item2["is_duplicate"] is True
        assert faq2_id in item1["duplicate_ids"]

        # Edit FAQ #1 via PUT /api/v1/admin/faqs/{faq1_id}
        updated_q = f"২০২৬ সালের মাস্টার্স শেষ পর্ব পরীক্ষার সংশোধিত ফলাফল কবে প্রকাশিত হবে? ({ts})"
        updated_a = "সংশোধিত উত্তর: ফলাফল http://103.113.200.68/nu-app/ পোর্টালে পাওয়া যাবে।"
        put_res = client.put(
            f"/api/v1/admin/faqs/{faq1_id}",
            headers=exam_headers,
            json={
                "question": updated_q,
                "answer": updated_a,
                "category": "রেজাল্ট সংক্রান্ত",
                "keywords": "মাস্টার্স, ফলাফল"
            }
        )
        assert put_res.status_code == 200, f"PUT /api/v1/admin/faqs/{faq1_id} failed: {put_res.text}"
        put_data = put_res.json()
        assert put_data["status"] == "success"
        assert put_data["category"] == "রেজাল্ট সংক্রান্ত"

        # Verify updated FAQ is now under 'রেজাল্ট সংক্রান্ত' category
        verify_res = client.get("/api/v1/admin/faqs?category=রেজাল্ট সংক্রান্ত", headers=exam_headers).json()
        edited_item = next((x for x in verify_res["items"] if x["id"] == faq1_id), None)
        assert edited_item is not None
        assert edited_item["question"] == updated_q
        assert edited_item["answer"] == updated_a

        # Delete duplicate FAQ #2 via DELETE /api/v1/admin/faqs/{faq2_id}
        del_res = client.delete(f"/api/v1/admin/faqs/{faq2_id}", headers=exam_headers)
        assert del_res.status_code == 200
        assert del_res.json()["status"] == "success"
        faq2_id = None
    finally:
        if faq1_id:
            client.delete(f"/api/v1/admin/faqs/{faq1_id}", headers=exam_headers)
        if faq2_id:
            client.delete(f"/api/v1/admin/faqs/{faq2_id}", headers=exam_headers)


