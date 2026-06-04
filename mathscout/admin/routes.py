from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="mathscout/templates")
router = APIRouter()


@router.get("")
@router.get("/")
def dashboard(request: Request):
    cards = [
        {"label": "AI Command", "value": "0", "href": "/admin/command"},
        {"label": "Techniques", "value": "0", "href": "/admin/techniques"},
        {"label": "Knowledge", "value": "0", "href": "/admin/knowledge"},
        {"label": "Source Sites", "value": "0", "href": "/admin/sources"},
        {"label": "Crawl Jobs", "value": "0", "href": "/admin/crawl-jobs"},
        {"label": "Documents", "value": "0", "href": "/admin/documents"},
        {"label": "Review Queue", "value": "0", "href": "/admin/review"},
        {"label": "Changes", "value": "0", "href": "/admin/changes"},
    ]
    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={"cards": cards},
    )


@router.get("/command")
def command_center(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="admin/placeholder.html",
        context={
            "title": "AI Command Center",
            "items": [
                "Natural-language goal input",
                "Current AI plan",
                "Pause, resume, and redirect controls",
                "Agent decision audit feed",
            ],
        },
    )


@router.get("/techniques")
def technique_library(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="admin/placeholder.html",
        context={
            "title": "Technique Library",
            "items": [
                "Canonical problem-solving techniques",
                "Teacher/source variants",
                "Knowledge-point mappings",
                "Manual edit and lock controls",
            ],
        },
    )


@router.get("/knowledge")
def knowledge_browser(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="admin/placeholder.html",
        context={
            "title": "Knowledge Browser",
            "items": [
                "Textbook tree",
                "Knowledge points",
                "Mapped techniques",
                "Manual course-mapping corrections",
            ],
        },
    )


@router.get("/review")
def review_queue(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="admin/placeholder.html",
        context={
            "title": "Review Queue",
            "items": [
                "AI-created candidates",
                "Proposed updates",
                "Conflicts",
                "Approve, reject, rewrite, merge, split",
            ],
        },
    )


@router.get("/changes")
def change_log(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="admin/placeholder.html",
        context={
            "title": "Change Log",
            "items": [
                "Human edit history",
                "AI decision history",
                "Before and after payloads",
                "Rollback candidates",
            ],
        },
    )
