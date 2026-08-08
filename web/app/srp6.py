"""Recompute an AzerothCore SRP6 verifier so a password can be checked offline.

WHY THIS IS NOT AN SRP HANDSHAKE
--------------------------------
SRP exists so a *client* can prove knowledge of a password without the password
crossing the wire. The portal is the server side and the password arrives in the POST
body over TLS, so there is nothing to negotiate: the account row already stores the
salt and the verifier, and

    v = g ^ H(s || H(UPPER(user) || ':' || UPPER(pass))) mod N

is a pure function of the three things we have. Recompute it, compare, done. No
ephemeral keys, no session state, no writes to acore_auth.

EVERY CONSTANT AND BYTE ORDER BELOW IS AZEROTHCORE'S, VERIFIED AGAINST THE SOURCE
--------------------------------------------------------------------------------
src/common/Cryptography/Authentication/SRP6.cpp:

    static std::array<uint8, 1>  const g = { 7 };
    static std::array<uint8, 32> const N = HexStrToByteArray<32>("894B...9BB7", true);
    Verifier CalculateVerifier(username, password, salt) {
        return _g.ModExp(SHA1::GetDigestOf(salt, SHA1::GetDigestOf(username, ":", password)),
                         _N).ToByteArray<32>();
    }

src/common/Cryptography/BigNumber.h / .cpp — the two endianness decisions that make or
break this, both of which default to LITTLE endian and are therefore easy to miss:

    BigNumber(Container const&, bool littleEndian = true)   -> BN_lebin2bn
    ToByteArray<Size>(bool littleEndian = true)             -> BN_bn2lebinpad

So the SHA1 digest that becomes the exponent x is read little-endian, and the 32-byte
verifier is written little-endian. Get either backwards and every login fails with a
verifier that looks plausible.

src/server/game/Accounts/AccountMgr.cpp:53 uppercases BOTH strings before hashing, with
Utf8ToUpperOnlyLatin — which maps *only* U+0061..U+007A (Util.h wcharToUpperOnlyLatin ->
isBasicLatinCharacter). That is why this module uppercases bytes by hand instead of
calling str.upper(): Python would also fold 'ß' to 'SS' and 'ı' to 'I', changing the
length and the bytes of the hashed string, and the resulting verifier would not match
the one the game server computed for the same password.
"""

from __future__ import annotations

import hashlib
import hmac

# The WoW 1.12+/WotLK SRP prime and generator. Not a secret, not configurable.
N = 0x894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7
G = 7

SALT_LEN = 32
VERIFIER_LEN = 32


def upper_latin(text: str) -> bytes:
    """UTF-8 encode, then uppercase ASCII a-z only — AzerothCore's Utf8ToUpperOnlyLatin.

    Operating on bytes is safe for UTF-8: a continuation byte is always >= 0x80, so no
    multi-byte sequence can contain a byte in the 0x61..0x7A range this touches.
    """
    return bytes(b - 32 if 0x61 <= b <= 0x7A else b for b in text.encode("utf-8"))


def calculate_verifier(username: str, password: str, salt: bytes) -> bytes:
    """v = g ^ H(salt || H(UPPER(user) || ':' || UPPER(pass))) mod N, 32 bytes LE."""
    if len(salt) != SALT_LEN:
        raise ValueError(f"salt must be {SALT_LEN} bytes, got {len(salt)}")
    inner = hashlib.sha1(upper_latin(username) + b":" + upper_latin(password)).digest()
    x = int.from_bytes(hashlib.sha1(salt + inner).digest(), "little")
    return pow(G, x, N).to_bytes(VERIFIER_LEN, "little")


def verify_password(username: str, password: str, salt: bytes, verifier: bytes) -> bool:
    """Constant-time check of a submitted password against a stored salt+verifier.

    Constant-time in the comparison only. The modexp above runs in time that depends on
    the exponent, but the exponent is a SHA1 digest of secrets the attacker is trying to
    guess, not something they can steer, so there is no oracle there. What compare_digest
    buys is that a *nearly* correct verifier does not take measurably longer to reject
    than a wildly wrong one.
    """
    if len(salt) != SALT_LEN or len(verifier) != VERIFIER_LEN:
        return False
    return hmac.compare_digest(calculate_verifier(username, password, salt), verifier)


def dummy_verify(username: str, password: str) -> None:
    """Burn the same work as a real check, for usernames that do not exist.

    Without this, "no such account" returns in microseconds while a real account costs a
    modexp, and the response time alone tells an attacker which of your friends' names
    are registered. The result is deliberately discarded.
    """
    calculate_verifier(username, password, b"\x00" * SALT_LEN)
