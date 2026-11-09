def can_delete_post(user, post) -> bool:
    return user.is_admin or post.author_id == user.id
