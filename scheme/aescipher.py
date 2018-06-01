#!/siq/bin/python

from spire.support.logs import LogHelper
from mesh.standard import OperationError

import binascii
import os
import types
import traceback
from siqhashlib.hashlib import pySSL

DEFAULT_KEY_FILE = '/etc/siq/siqkwd'

log = LogHelper('spire')

#
# This class borrowed from dataserver/parts/common/aescipher.py
#
class AESCipher():
    def __init__ (self, keyfile=DEFAULT_KEY_FILE):
        self._keyfile = keyfile
        self._tempfile = None

    def encrypt(self, plaintext, stable=False):
        result = plaintext
        log('info', 'Going to encrypt text')
        if plaintext:
            if isinstance(plaintext, unicode):
                # swig wrapper for _xssl.so won't currently marshal unicode strings
                plaintext = plaintext.encode('utf-8')

            try:
                version, key, iv = self.getKey()
                if not key or not iv:
                    # the key must have been tempered with
                    self.generateNewKey()
                    version, key, iv = self._getKey()

                if key and iv:
                    pyssl = pySSL.getInstance()
                    # encrypt using default cipher, passcode (key+iv), with salt, base64-encoded results
                    # (note the passcode is generated from key+iv for backward compatibility)
                    passcode = key+iv
		    if stable:
		        encryptedText = pyssl.encrypt_passcode(plaintext, passcode, True, use_salt=False)
		    else:
                    	encryptedText = pyssl.encrypt_passcode(plaintext, passcode, True)
                    # format: VVV(key version) + encryptedText
                    result = self._toHex(version>>8)[1] + self._toHex(version & 0xff) + encryptedText
                else:
                    log('error', 'Failed to encrypt data! Plain-text is returned!')
            except:
                log('error', 'Exception, failed to encrypt data! Plain-text is returned!')
                raise OperationError('Exception, Failed to encrypt data! Plain-text is returned!')

        return result

    def decrypt(self, encryptedText):
        log('info', 'Going to decrypt text')
        plaintext = encryptedText
        if encryptedText:
            try:
                plaintext = self._decrypt(encryptedText)
            except:
                log('error', 'Failed to decrypt data! Encrypted text is returned!')
                raise OperationError('Failed to decrypt data! Encrypted text is returned!')

        return plaintext

    def _decrypt(self, encryptedText):
        version = int(encryptedText[0:3])
        plaintext = encryptedText
        version, key, iv = self.getKey(version)
        if key and iv:
            pyssl = pySSL.getInstance()
            # decrypt using default cipher, passcode (key+iv), base64-encoded input
            # (note the passcode is generated from key+iv for backward compatibility)
            passcode = key+iv
            plaintext = pyssl.decrypt_passcode(encryptedText[3:], passcode, True)
        else:
            log('error', 'Failed to decrypt data! Encrypted text is returned!')
        return plaintext

    def isEncrypted (self, pwd):
        if pwd:
            try:
                if len(pwd) > 3:
                    v = int(pwd[:3])
                    self._decrypt(pwd)
                    result = True
                else:
                    result = False
            except:
                result = False
        else:
            result = True
        return result

    def getKey (self, version=None):
        try:
            size = os.stat(self._keyfile)
        except OSError:
            self.generateNewKey()
        return self._getKey(version)

    def generateNewKey (self):
        key = None
        iv = None
        fg = None

        try:
            try:
                fg = open('/dev/urandom', 'r')
                key = fg.read(32)
                iv = fg.read(16)
            except:
                log('error', 'Failed to generate new key!')
                raise OperationError('Failed to generate new key!')
        finally:
            if fg:
                fg.close()

        if key and iv:
            version, k, i = self._getKey()
            if not version:
                version = 0
            version += 1
            f = None
            try:
                key = self._charArrayToHex(key)
                iv = self._charArrayToHex(iv)
                try:
                    ln = self._getKeyString(version, key, iv)
                    # obscure it more by adding the crc to the end of the string
                    ln += self._getCrcString(ln)
                    try:
                        size = os.stat(self._keyfile)
                    except OSError:
                        size = 0
                    f = open(self._keyfile, 'a+')
                    if size:
                        f.write('\n')
                    f.write(ln)
                    # this will cause failure in appstack
                    # but if don't change mode to 0600, will it be insecure?
                    # os.chmod(self._keyfile, 0600)
                except:
                    log('error', 'Failed to write generated key!')
                    raise OperationError('Failed to write generated key!')
                    key = None
                    iv = None
            finally:
                if f:
                    f.close()

        log('info', 'Key generated at key file '+self._keyfile)

        return (key, iv)

    def _hexToIntArray(self, harray):
        arr = []
        i = 0
        while i < len(harray):
            h = harray[i:i+2]
            arr.append(int(h, 16))
            i += 2
        return arr

    def _charArrayToHex (self, carray):
        arr = ''
        for c in carray:
            arr += self._toHex(ord(c))
        return arr

    def _toHex(self, n):
        h = self._to_upper(hex(n)[2:])
        if len(h) < 2:
            return '0'+h
        return h

    def _getKey (self, version=None):
        keys = {}
        key = None
        iv = None
        f = None
        try:
            try:
                f = open(self._keyfile, 'r')
                k = f.readline()
                while len(k):
                    k = k.strip()
                    if len(k) > 0:
                        (v, key) = k.split('\t')
                        crc = key[-9:]
                        iv = key[:32]
                        key = key[32:-9]
                        keys[int(v)] = (key, iv, crc)
                    k = f.readline()
            except:
                traceback.print_exc()
                log('error', 'Failed to get key!')
                raise OperationError('Failed to get key!')
        finally:
            if f:
                f.close()
        if keys:
            if version is not None:
                if keys.has_key(version):
                    key, iv, crc = keys[version]
                else:
                    log('error', 'Could not find key version: %d!', version)

            else:
                v = keys.keys()
                v.sort()
                version = v[len(v)-1]
                key, iv, crc = keys[version]

            ln = self._getKeyString(version, key, iv)
            if int(crc, 16) != binascii.crc32(ln):
                log('error', 'Invalid key string due to CRC check!')
                key = None
                iv = None
        else:
            log('error', 'Could not find suitable key!')

        return (version, key, iv)

    def _getKeyString (self, version, key, iv):
        # obscure it more by putting the iv, and the key into one string
        ln = self._to_string(version) + '\t' + iv + key
        return ln

    def _getCrcString (self, ln):
        crc = binascii.crc32(ln)
        if crc >= 0:
            res = '+'
        else:
            res = '-'
        h = self._to_upper(hex(abs(crc))[2:])
        h = '0'*(8-len(h)) + h
        res += h
        return res

    def _to_upper(self, val):
        val = self._to_unicode(val).upper()
        return self._to_string(val)

    # _to_unicode
    # _to_string
    # is_instance_method
    # These 3 methods are copied from dataserver/parts/common/safestring.py
    def _to_unicode(self, val, force=False):
        if val is None:
            return 'None'

        if not isinstance(val, basestring):
            # Must do the checks in this order because most every object supports __str__.
            if hasattr(val, '__unicode__') and self.is_instance_method(val.__unicode__):
                val = val.__unicode__()
            elif hasattr(val, '__str__') and self.is_instance_method(val.__str__):
                val = val.__str__()
            else:
                val = '%s' % (val,)

        if force:
            if isinstance(val, str):
                return val.decode('utf-8')
            return val

        if isinstance(val, str):
            for x in val:
                if ord(x) > 127:
                    return val.decode('utf-8')
            return val

        else: # unicode
            # In timing tests, this takes very little time and ensures that values
            # that don't require unicode are returned as ascii str objects.
            for x in val:
                if ord(x) > 127:
                    return val
            return val.encode('ascii')

    def _to_string(self, val):
        if val is None:
            return 'None'

        if not isinstance(val, basestring):
            # Must do the checks in this order because most every object supports __str__.
            if hasattr(val, '__unicode__') and self.is_instance_method(val.__unicode__):
                val = val.__unicode__()
            elif hasattr(val, '__str__') and self.is_instance_method(val.__str__):
                val = val.__str__()
            else:
                val = '%s' % (val,)

        if isinstance(val, str):
            return val
        else: # unicode
            return val.encode('utf-8')

    def is_instance_method(self, obj):
        """Checks if an object is a bound method on an instance.
        """
        if not isinstance(obj, types.MethodType):
            return False # Not a method
        if obj.im_self is None:
            return False # Method is not bound
        if issubclass(obj.im_class, type) or obj.im_class is types.ClassType:
            return False # Method is a classmethod
        return True


def prepareKeyFile():
    # Do the Right Thing with the keyfile.
    #
    # On a standalone, generate a new one if it doesn't exist.
    #
    AESCipher().getKey()
    return


if __name__ == "__main__":
    import sys
    import pdb
    #pdb.set_trace()

    encrypt = False
    decrypt = False
    new_key = False
    get_key = False
    prepare = False
    found = False
    keyfile = None

    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == '-encrypt':
            encrypt = True
            inp = sys.argv[i+1]
            found = True
            break
        elif sys.argv[i] == '-prepare':
            prepare = True
            found = True
            keyfile = DEFAULT_KEY_FILE
            break
        elif sys.argv[i] == '-decrypt':
            decrypt = True
            inp = sys.argv[i+1]
            found = True
            break
        elif sys.argv[i] == '-generate_key':
            new_key = True
            found = True
        elif sys.argv[i] == '-get_current_key':
            get_key = True
            found = True
        elif sys.argv[i] == '-keystore':
            keyfile = sys.argv[i+1]
            i = i + 1
        i = i + 1

    if not found or keyfile is None:
        print 'Usage:', sys.argv[0], '-keystore <keystore name> [-encrypt <plain-text> | -decrypt <enrypted text> | -generate_key | -get_current_key]'
        sys.exit(0)

    if prepare:
        prepareKeyFile()
        sys.exit(0)

    sslp = AESCipher(keyfile)
    if encrypt:
        ciph = sslp.encrypt(inp)
        print ciph
    elif decrypt:
        decr = sslp.decrypt(inp)
        print decr
    elif new_key:
        print sslp.generateNewKey()
    elif get_key:
        print sslp.getKey()

