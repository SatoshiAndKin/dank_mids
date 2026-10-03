import pytest

from dank_mids.helpers.hashing import AttributeDict


def test_attribute_dict_hash_is_cached_and_values_remain_immutable():
    value = AttributeDict({"key": (1, 2)})
    assert hash(value) == hash(AttributeDict({"key": (1, 2)}))
    assert hash(value) == hash(value)
    with pytest.raises(TypeError, match="immutable"):
        value.key = 3
    assert value["key"] == (1, 2)
