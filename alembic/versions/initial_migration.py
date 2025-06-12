from alembic import op
import sqlalchemy as sa

revision = 'initial_migration'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'user_values',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('value', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

def downgrade():
    op.drop_table('user_values')