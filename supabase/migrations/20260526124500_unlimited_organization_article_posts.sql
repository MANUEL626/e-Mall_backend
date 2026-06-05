alter table public.organization_article_posts
    drop constraint if exists organization_article_posts_slot_range;

alter table public.organization_article_posts
    add constraint organization_article_posts_slot_positive
    check (slot >= 1);

comment on table public.organization_article_posts is
    'Contenus promo (image/video + legende) par article ; au plus une ligne par (article, slot), sans limite haute de slot.';

