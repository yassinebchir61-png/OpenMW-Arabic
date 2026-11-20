#!/usr/bin/env python3
import sys
from pathlib import Path

src = Path(sys.argv.pop(1))
toutf8_dir = src / "components/toutf8"

entries = []
for b in range(256):
    try:
        utf8_bytes = bytes([b]).decode("cp1256").encode("utf-8")
    except UnicodeDecodeError:
        utf8_bytes = b" "
    length = len(utf8_bytes)
    signed_vals = [v - 256 if v > 127 else v for v in utf8_bytes]
    row = [length] + signed_vals + list((0,)) * (5 - length)
    entries.append(", ".join(str(x) for x in row))

table_code = "\n    const static signed char windows_1256[] = {\n        " + ",\n        ".join(entries) + "\n    };\n"

t_path = toutf8_dir / "tablesgen.hpp"
t_txt = t_path.read_text(encoding="utf-8")
if "windows_1256" not in t_txt:
    idx = t_txt.rfind("}")
    t_path.write_text(t_txt[:idx] + table_code + t_txt[idx:], encoding="utf-8")

h_path = toutf8_dir / "toutf8.hpp"
h_txt = h_path.read_text(encoding="utf-8")
if "WINDOWS_1256" not in h_txt:
    h_path.write_text(h_txt.replace("WINDOWS_1252,", "WINDOWS_1252,\n        WINDOWS_1256,"), encoding="utf-8")

c_path = toutf8_dir / "toutf8.cpp"
c_txt = c_path.read_text(encoding="utf-8")

icu_includes = """#include <unicode/ubidi.h>
#include <unicode/ushape.h>
#include <unicode/ustring.h>
#include <vector>
"""

icu_helper = """
    void shapeArabicUtf8(std::string& buffer, std::size_t& outlen, ToUTF8::BufferAllocationPolicy policy)
    {
        UErrorCode status = U_ZERO_ERROR;
        int32_t u16Len = 0;
        u_strFromUTF8(nullptr, 0, &u16Len, buffer.data(), static_cast<int32_t>(outlen), &status);
        if (status != U_BUFFER_OVERFLOW_ERROR && U_FAILURE(status))
            return;

        status = U_ZERO_ERROR;
        std::vector<UChar> u16Src(u16Len + 1, 0);
        u_strFromUTF8(u16Src.data(), u16Len + 1, nullptr, buffer.data(), static_cast<int32_t>(outlen), &status);
        if (U_FAILURE(status))
            return;

        std::vector<UChar> u16Shaped(u16Len * 2 + 16, 0);
        int32_t shapedLen = u_shapeArabic(
            u16Src.data(), u16Len, u16Shaped.data(), static_cast<int32_t>(u16Shaped.size()),
            U_SHAPE_LETTERS_SHAPE | U_SHAPE_TEXT_DIRECTION_LOGICAL | U_SHAPE_LENGTH_GROW_SHRINK, &status);
        if (U_FAILURE(status))
        {
            status = U_ZERO_ERROR;
            u16Shaped = u16Src;
            shapedLen = u16Len;
        }

        std::vector<UChar> u16Visual;
        u16Visual.reserve(shapedLen + 16);
        UBiDi* bidi = ubidi_open();
        if (bidi)
        {
            int32_t start = 0;
            while (start <= shapedLen)
            {
                int32_t end = start;
                while (end < shapedLen && u16Shaped[end] != u'\\n' && u16Shaped[end] != u'\\r')
                    ++end;

                int32_t lineLen = end - start;
                if (lineLen > 0)
                {
                    status = U_ZERO_ERROR;
                    ubidi_setPara(bidi, u16Shaped.data() + start, lineLen, UBIDI_DEFAULT_RTL, nullptr, &status);
                    if (U_SUCCESS(status))
                    {
                        std::vector<UChar> lineOut(lineLen + 8, 0);
                        int32_t reorderedLen = ubidi_writeReordered(
                            bidi, lineOut.data(), static_cast<int32_t>(lineOut.size()),
                            UBIDI_DO_MIRRORING | UBIDI_REMOVE_BIDI_CONTROLS, &status);
                        if (U_SUCCESS(status) && reorderedLen > 0)
                            u16Visual.insert(u16Visual.end(), lineOut.begin(), lineOut.begin() + reorderedLen);
                        else
                            u16Visual.insert(u16Visual.end(), u16Shaped.begin() + start, u16Shaped.begin() + end);
                    }
                    else
                    {
                        u16Visual.insert(u16Visual.end(), u16Shaped.begin() + start, u16Shaped.begin() + end);
                    }
                }

                if (end < shapedLen)
                {
                    u16Visual.push_back(u16Shaped[end]);
                    start = end + 1;
                }
                else
                {
                    break;
                }
            }
            ubidi_close(bidi);
        }
        else
        {
            u16Visual.assign(u16Shaped.begin(), u16Shaped.begin() + shapedLen);
        }

        status = U_ZERO_ERROR;
        int32_t finalUtf8Len = 0;
        u_strToUTF8(nullptr, 0, &finalUtf8Len, u16Visual.data(), static_cast<int32_t>(u16Visual.size()), &status);
        if (status != U_BUFFER_OVERFLOW_ERROR && U_FAILURE(status))
            return;

        status = U_ZERO_ERROR;
        outlen = static_cast<std::size_t>(finalUtf8Len);
        resize(outlen, policy, buffer);
        u_strToUTF8(buffer.data(), static_cast<int32_t>(buffer.size()), nullptr, u16Visual.data(), static_cast<int32_t>(u16Visual.size()), &status);
        if (U_SUCCESS(status))
            buffer[outlen] = 0;
    }
"""

if "WINDOWS_1256" not in c_txt:
    c_txt = c_txt.replace('#include "toutf8.hpp"', '#include "toutf8.hpp"\n' + icu_includes)
    c_txt = c_txt.replace(
        "case ToUTF8::WINDOWS_1251:\n                return { ToUTF8::windows_1251, std::size(ToUTF8::windows_1251) };",
        "case ToUTF8::WINDOWS_1251:\n                return { ToUTF8::windows_1251, std::size(ToUTF8::windows_1251) };\n            case ToUTF8::WINDOWS_1256:\n                return { ToUTF8::windows_1256, std::size(ToUTF8::windows_1256) };"
    )
    c_txt = c_txt.replace(
        "StatelessUtf8Encoder::StatelessUtf8Encoder(FromType sourceEncoding)",
        icu_helper + "\nStatelessUtf8Encoder::StatelessUtf8Encoder(FromType sourceEncoding)"
    )
    c_txt = c_txt.replace(
        "    assert(buffer[outlen] == 0);\n\n    return std::string_view(buffer.data(), outlen);",
        "    assert(buffer[outlen] == 0);\n\n    std::size_t finalLen = outlen;\n    if (mTranslationArray.data() == ToUTF8::windows_1256)\n        shapeArabicUtf8(buffer, finalLen, bufferAllocationPolicy);\n\n    return std::string_view(buffer.data(), finalLen);"
    )
    c_txt = c_txt.replace(
        'else if (encodingName == "win1252")\n        return ToUTF8::WINDOWS_1252;',
        'else if (encodingName == "win1252")\n        return ToUTF8::WINDOWS_1252;\n    else if (encodingName == "win1256")\n        return ToUTF8::WINDOWS_1256;'
    )
    c_txt = c_txt.replace(
        'else if (encodingName == "win1252")\n        return "Using default (English) font encoding.";',
        'else if (encodingName == "win1252")\n        return "Using default (English) font encoding.";\n    else if (encodingName == "win1256")\n        return "Using Arabic font encoding.";'
    )
    c_path.write_text(c_txt, encoding="utf-8")

print("Applied Arabic win1256 + ICU Shaping/BiDi successfully!")

import shutil
font_src = Path(__file__).resolve().parent / "DejaVuSans.ttf"
font_dst = src / "files/data/fonts/DejaVuLGCSansMono.ttf"
if font_src.exists() and font_dst.parent.exists():
    shutil.copy2(font_src, font_dst)
    print("Replaced default font with full Arabic-capable DejaVuSans.ttf")
