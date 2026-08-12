# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Nimmo Smith Technologies Limited

from nicegui.testing import User


async def test_index_page_loads(user: User) -> None:
    await user.open("/")
    await user.should_see("pyopia-gui")
