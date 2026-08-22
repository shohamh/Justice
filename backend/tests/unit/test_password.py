from app.auth.password import _hasher, hash_password, verify_password


def test_hash_password_returns_string_with_argon2_prefix():
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")


def test_verify_password_accepts_correct_password():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h) is True


def test_verify_password_rejects_wrong_password():
    h = hash_password("correct horse battery staple")
    assert verify_password("wrong", h) is False


def test_hash_is_salted_so_two_hashes_of_same_password_differ():
    # Assert against the raw hasher: hash_password() memoizes per plaintext
    # under JUSTICE_TESTING=1, which would legitimately return equal strings.
    a = _hasher.hash("same")
    b = _hasher.hash("same")
    assert a != b
    assert verify_password("same", a)
    assert verify_password("same", b)


def test_verify_returns_false_on_malformed_hash():
    assert verify_password("anything", "not-a-real-hash") is False
