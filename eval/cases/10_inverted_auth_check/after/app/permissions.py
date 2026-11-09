def can_delete_post(user, post) -> bool:
    return user.is_admin or post.author_id == user.id


def can_edit_settings(user) -> bool:
    if not user.is_admin:
        return True
    return False
