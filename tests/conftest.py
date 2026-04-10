import sqlite3
import pytest


@pytest.fixture
def db_connection():
	from rust_dll_mcp.db import create_schema
	connection = sqlite3.connect(":memory:")
	connection.row_factory = sqlite3.Row
	create_schema(connection)
	yield connection
	connection.close()


SAMPLE_CS = """\
using System;
using System.Collections.Generic;

namespace Rust
{
	public class PlayerInventory : BaseEntity
	{
		public ItemContainer containerMain;
		public int capacity = 24;

		public void GiveItem(Item item, int amount = 1)
		{
			containerMain.AddItem(item, amount);
		}

		public bool HasItem(int itemID)
		{
			return containerMain.FindItemByItemID(itemID) != null;
		}

		public int GetAmount(int itemID)
		{
			return containerMain.GetAmount(itemID, false);
		}
	}
}
"""
