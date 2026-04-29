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
    addr = characters.GetValueAsUnsigned()
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


def ak_atomic_summary(valobj, internal_dict):
    value = valobj.GetChildMemberWithName("m_value")
    return value.GetSummary() or value.GetValueAsUnsigned()


def ak_fixedarray_summary(valobj, internal_dict):
    valobj = valobj.GetNonSyntheticValue()
    size = valobj.GetChildMemberWithName("m_size").GetValueAsUnsigned()
    return f"{valobj.GetTypeName()} size={size}"


class AKFixedArraySynthProvider:
    def __init__(self, valobj, internal_dict):
        self.valobj = valobj
        self.update()

    def update(self):
        self.size = self.valobj.GetChildMemberWithName("m_size").GetValueAsUnsigned()
        self.elements = self.valobj.GetChildMemberWithName("m_elements")
        self.element_type = self.elements.GetType().GetPointeeType()
        self.element_size = self.element_type.GetByteSize()

    def has_children(self):
        return self.size > 0

    def num_children(self):
        return self.size

    def get_child_index(self, name):
        if not name.startswith("[") or not name.endswith("]"):
            return -1
        try:
            return int(name[1:-1])
        except ValueError:
            return -1

    def get_child_at_index(self, index):
        if index < 0 or index >= self.num_children():
            return None
        if self.elements.GetValueAsUnsigned() == 0:
            return None
        return self.elements.CreateChildAtOffset(
            f"[{index}]",
            index * self.element_size,
            self.element_type,
        )

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
    debugger.HandleCommand(
        "type summary add -x \"^AK::Atomic(<.*>)?$\" -F ak.ak_atomic_summary"
    )
    debugger.HandleCommand(
        "type summary add -x \"^AK::FixedArray(<.*>)?$\" -F ak.ak_fixedarray_summary"
    )
    debugger.HandleCommand(
        "type synthetic add -x \"^AK::FixedArray(<.*>)?$\" -l ak.AKFixedArraySynthProvider"
    )
