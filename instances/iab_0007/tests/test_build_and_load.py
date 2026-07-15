from support import contract
def test_cmake_build_and_dynamic_load(): assert contract().library is not None
