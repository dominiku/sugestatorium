from __future__ import annotations

from pathlib import Path

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from .store import (
    REVIEW_ACTIONS,
    REVIEW_STATUSES,
    create_prompt,
    get_dashboard,
    get_global_review_region,
    get_insights,
    get_prompt,
    get_run_region,
    get_suggestion_detail,
    import_run,
    list_prompts,
    parse_filters,
    search,
    update_review,
)

bp = Blueprint("pages", __name__)


def root_path() -> Path:
    return current_app.config["ROOT_PATH"]


@bp.context_processor
def inject_globals() -> dict[str, object]:
    return {
        "review_statuses": REVIEW_STATUSES,
        "review_actions": REVIEW_ACTIONS,
    }


@bp.get("/")
def home() -> str:
    dashboard = get_dashboard(root_path())
    return render_template("home.html", dashboard=dashboard, active_nav="home")


@bp.post("/imports")
def imports() -> Response:
    prompt_id = request.form.get("prompt_id", "")
    note = request.form.get("note", "")
    workspace_file = request.form.get("workspace_file", "")
    uploaded = request.files.get("upload")

    try:
        if uploaded and uploaded.filename:
            run_id = import_run(
                root_path(), uploaded.filename, uploaded.read(), prompt_id, note
            )
        elif workspace_file:
            csv_path = root_path() / workspace_file
            run_id = import_run(
                root_path(), csv_path.name, csv_path.read_bytes(), prompt_id, note
            )
        else:
            raise ValueError("Choose a workspace CSV or upload a new one.")
    except Exception as error:  # noqa: BLE001
        flash(str(error), "error")
        return redirect(url_for("pages.home"))

    flash("Batch imported successfully.", "success")
    return redirect(url_for("pages.run_detail", run_id=run_id))


@bp.get("/prompts")
def prompts() -> str:
    prompts_list = list_prompts(root_path())
    selected_prompt_id = request.args.get("prompt_id") or (
        prompts_list[0]["id"] if prompts_list else ""
    )
    selected_prompt = (
        get_prompt(root_path(), selected_prompt_id) if selected_prompt_id else None
    )
    runs = get_dashboard(root_path())["runs"]
    return render_template(
        "prompts.html",
        prompts=prompts_list,
        selected_prompt=selected_prompt,
        runs=runs,
        active_nav="prompts",
    )


@bp.post("/prompts/create")
def prompts_create() -> Response:
    payload = {
        "name": request.form.get("name", ""),
        "model": request.form.get("model", ""),
        "temperature": request.form.get("temperature", "0.2"),
        "notes": request.form.get("notes", ""),
        "content": request.form.get("content", ""),
    }
    try:
        prompt = create_prompt(root_path(), payload)
    except Exception as error:  # noqa: BLE001
        flash(str(error), "error")
        return redirect(url_for("pages.prompts"))
    flash("Prompt added successfully.", "success")
    return redirect(url_for("pages.prompts", prompt_id=prompt["id"]))


@bp.get("/runs/<run_id>")
def run_detail(run_id: str) -> str:
    filters = parse_filters(request.args)
    region = get_run_region(root_path(), run_id, filters)
    if not region:
        return render_template("not_found.html", active_nav="home"), 404
    return render_template("run.html", region=region, active_nav="home")


@bp.get("/runs/<run_id>/review-region")
def run_review_region(run_id: str) -> str:
    filters = parse_filters(request.args)
    region = get_run_region(root_path(), run_id, filters)
    if not region:
        return ""
    return render_template("partials/run_review_region.html", region=region)


@bp.get("/insights")
def insights() -> str:
    insights_snapshot = get_insights(root_path())
    filters = parse_filters(request.args)
    review_region = get_global_review_region(root_path(), filters, reviewed_only=True)
    return render_template(
        "insights.html",
        insights=insights_snapshot,
        review_region=review_region,
        page_path=url_for("pages.insights"),
        active_nav="insights",
    )


@bp.get("/insights/reviews")
def insights_reviews() -> str:
    insights_snapshot = get_insights(root_path())
    filters = parse_filters(request.args)
    review_region = get_global_review_region(root_path(), filters, reviewed_only=False)
    heading = "Reviewed rows"
    if filters["status"] != "all":
        heading = f"Rows with review status {filters['status']}"
    elif filters["rule"] != "all":
        heading = f"Rows for rule {filters['rule']}"
    return render_template(
        "insights_reviews.html",
        insights=insights_snapshot,
        review_region=review_region,
        heading=heading,
        page_path=url_for("pages.insights_reviews"),
        active_nav="insights",
    )


@bp.get("/reviews/global-region")
def global_review_region() -> str:
    filters = parse_filters(request.args)
    reviewed_only = request.args.get("reviewed_only", "1") == "1"
    region = get_global_review_region(root_path(), filters, reviewed_only=reviewed_only)
    page_path = request.args.get("page_path") or url_for("pages.insights")
    return render_template(
        "partials/global_review_region.html",
        region=region,
        reviewed_only=reviewed_only,
        page_path=page_path,
    )


@bp.get("/search")
def search_results() -> str:
    results = search(root_path(), request.args.get("q", ""))
    return render_template("partials/search_results.html", results=results)


@bp.get("/suggestions/<int:suggestion_id>/drawer")
def suggestion_drawer(suggestion_id: int) -> str:
    suggestion = get_suggestion_detail(root_path(), suggestion_id)
    if not suggestion:
        return ""
    return render_template("partials/drawer.html", suggestion=suggestion)


@bp.post("/reviews/<int:suggestion_id>/update")
def review_update(suggestion_id: int) -> Response:
    update_review(
        root_path(),
        suggestion_id,
        {"field": request.form.get("field"), "value": request.form.get("value")},
    )
    return Response(status=204)


@bp.get("/health")
def health() -> Response:
    return Response("ok", mimetype="text/plain")
