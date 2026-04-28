import lldb
import debugpy

def connect(debugger, command, result, internal_dict):
    debugpy.listen(("localhost", 5678))
    print("Waiting for debugger to attach...")
    debugpy.wait_for_client()
    print("Debugger attached.")


def ak_string_impl_summary(valobj, internal_dict):
    length = valobj.GetChildMemberWithName("m_length").GetValueAsUnsigned()
    if length == 0:
        return '""'

    data = valobj.GetChildMemberWithName("m_inline_buffer")
    arr = data.GetPointeeData(0, length).uint8s
    return bytes(arr).decode("utf-8", "replace")


def ak_bytestring_summary(valobj, internal_dict):
    impl_ptr = valobj.GetChildMemberWithName("m_impl") \
        .GetChildMemberWithName("m_ptr")

    if impl_ptr.GetValueAsUnsigned() == 0:
        return '""'

    impl = impl_ptr.Dereference()
    return ak_string_impl_summary(impl, internal_dict)


def ak_stringview_summary(valobj, internal_dict):
    length = valobj.GetChildMemberWithName("m_length").GetValueAsUnsigned()
    if length == 0:
        return '""'

    characters = valobj.GetChildMemberWithName("m_characters")
    arr = characters.GetPointeeData(0, length).uint8s
    return '"' + bytes(arr).decode("utf-8", "replace") + '"'


def ak_string_summary(valobj, internal_dict):
    stream = lldb.SBStream()
    if not valobj.GetExpressionPath(stream):
        return None

    frame = valobj.GetFrame()
    if not frame.IsValid():
        return None

    string_view = frame.EvaluateExpression(
        f"{stream.GetData()}.bytes_as_string_view()"
    )
    if not string_view.IsValid() or string_view.GetError().Fail():
        return None

    return ak_stringview_summary(string_view, internal_dict)

def __lldb_init_module(debugger, internal_dict):
    debugger.HandleCommand(
        "command script add -f ak.connect pyconnect --overwrite"
    )
    debugger.HandleCommand(
        "type summary add -x \"^AK::ByteString(<.*>)?$\" -F ak.ak_bytestring_summary"
    )
    debugger.HandleCommand(
        "type summary add -x \"^AK::ByteStringImpl(<.*>)?$\" -F ak.ak_string_impl_summary"
    )
    debugger.HandleCommand(
        "type summary add -x \"^AK::StringView(<.*>)?$\" -F ak.ak_stringview_summary"
    )
    debugger.HandleCommand(
        "type summary add -x \"^AK::String(<.*>)?$\" -F ak.ak_string_summary"
    )
