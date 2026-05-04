"""design canvas tables

Revision ID: 0002_canvas
Revises: 0001_initial
Create Date: 2026-05-04

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0002_canvas"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # designs.current_version_id -> design_versions.id and
    # design_versions.design_id -> designs.id form a cycle. Create both tables
    # without the cycle-closing FK first, then add it as a separate constraint.
    op.create_table(
        "designs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "current_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_designs_conversation_id_updated_at",
        "designs",
        ["conversation_id", "updated_at"],
    )
    op.create_index("ix_designs_user_id", "designs", ["user_id"])

    op.create_table(
        "design_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "design_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("designs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("design_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("html", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("edit_scope_selector", sa.Text(), nullable=True),
        sa.Column("model_used", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_design_versions_design_id_created_at",
        "design_versions",
        ["design_id", "created_at"],
    )

    # Close the cycle now that both tables exist.
    op.create_foreign_key(
        "fk_designs_current_version_id",
        "designs",
        "design_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "design_handoffs",
        sa.Column("code", sa.Text(), primary_key=True),
        sa.Column(
            "design_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("design_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_design_handoffs_expires_at", "design_handoffs", ["expires_at"]
    )

    op.add_column(
        "messages",
        sa.Column(
            "design_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("design_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "design_version_id")

    op.drop_index("ix_design_handoffs_expires_at", table_name="design_handoffs")
    op.drop_table("design_handoffs")

    # Drop the cycle-closing FK before either table so PG doesn't complain.
    op.drop_constraint(
        "fk_designs_current_version_id", "designs", type_="foreignkey"
    )

    op.drop_index(
        "ix_design_versions_design_id_created_at", table_name="design_versions"
    )
    op.drop_table("design_versions")

    op.drop_index("ix_designs_user_id", table_name="designs")
    op.drop_index(
        "ix_designs_conversation_id_updated_at", table_name="designs"
    )
    op.drop_table("designs")
