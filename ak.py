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


def ak_refcounted_summary(valobj, internal_dict):
    value = valobj.GetChildMemberWithName("m_ref_count")
    return value.GetSummary() or value.GetValue()


def ak_fixedarray_summary(valobj, internal_dict):
    valobj = valobj.GetNonSyntheticValue()
    size = valobj.GetChildMemberWithName("m_size").GetValueAsUnsigned()
    return f"size={size}"


def ak_hashmap_summary(valobj, internal_dict):
    valobj = valobj.GetNonSyntheticValue()
    table = valobj.GetChildMemberWithName("m_table")
    size = table.GetChildMemberWithName("m_size").GetValueAsUnsigned()
    return f"size={size}"


class AKFixedArraySynthProvider:
    def __init__(self, valobj, internal_dict):
        self.valobj = valobj.GetNonSyntheticValue()
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


class AKHashMapSynthProvider:
    def __init__(self, valobj, internal_dict):
        self.valobj = valobj.GetNonSyntheticValue()
        self.entries = []
        self.update()

    def update(self):
        self.entries = []

        table = self.valobj.GetChildMemberWithName("m_table")
        buckets = table.GetChildMemberWithName("m_buckets")
        size = table.GetChildMemberWithName("m_size").GetValueAsUnsigned()
        mask = table.GetChildMemberWithName("m_mask").GetValueAsUnsigned()

        if size == 0 or buckets.GetValueAsUnsigned() == 0:
            return

        entry_type = table.GetType().GetTemplateArgumentType(0)
        bucket_type = buckets.GetType().GetPointeeType()
        bucket_size = bucket_type.GetByteSize()
        target = self.valobj.GetTarget()

        for i in range(mask + 1):
            if len(self.entries) >= size:
                break

            bucket = buckets.CreateChildAtOffset(
                f"bucket[{i}]",
                i * bucket_size,
                bucket_type,
            )
            state = bucket.GetChildMemberWithName("state").GetValueAsUnsigned()
            if state == 0:
                continue

            storage = bucket.GetChildMemberWithName("storage")
            entry = bucket.CreateValueFromAddress(
                f"entry[{len(self.entries)}]",
                storage.GetAddress().GetLoadAddress(target),
                entry_type,
            )
            self.entries.append(entry)

    def has_children(self):
        return len(self.entries) > 0

    def num_children(self):
        return len(self.entries)

    def get_child_index(self, name):
        if name.startswith("[") and name.endswith("]"):
            try:
                return int(name[1:-1])
            except ValueError:
                return -1
        return -1

    def get_child_at_index(self, index):
        if index < 0 or index >= len(self.entries):
            return None

        entry = self.entries[index]
        key = entry.GetChildMemberWithName("key")
        val = entry.GetChildMemberWithName("value")

        key_str = key.GetSummary() or key.GetValue() or "?"
        key_str = key_str.strip('"')

        return val.Clone(f"[{key_str}]")

def ak_refptr_summary(valobj, internal_dict):
    m_ptr = valobj.GetChildMemberWithName("m_ptr")
    ptr_value = m_ptr.GetValueAsUnsigned()

    if ptr_value == 0:
        return "nullptr"

    pointee = m_ptr.Dereference()
    if pointee.IsValid():
        ref_count = pointee.GetChildMemberWithName("m_ref_count")
        if ref_count.IsValid():
            ref_count_val = ref_count.GetValueAsUnsigned()
            return f"(ref_count={ref_count_val}) {hex(ptr_value)}"
        return hex(ptr_value)
    return hex(ptr_value)


def ak_ownptr_summary(valobj, internal_dict):
    m_ptr = valobj.GetChildMemberWithName("m_ptr")
    ptr_value = m_ptr.GetValueAsUnsigned()

    if ptr_value == 0:
        return "nullptr"

    return hex(ptr_value)


def ak_nonnullrefptr_summary(valobj, internal_dict):
    valobj = valobj.GetNonSyntheticValue()
    m_ptr = valobj.GetChildMemberWithName("m_ptr")
    ptr_value = m_ptr.GetValueAsUnsigned()

    if ptr_value == 0:
        return "nullptr"

    pointee = m_ptr.Dereference()
    if pointee.IsValid():
        ref_count = pointee.GetChildMemberWithName("m_ref_count")
        if ref_count.IsValid():
            ref_count_val = ref_count.GetValueAsUnsigned()
            return f"{hex(ptr_value)} (ref_count={ref_count_val})"
        return hex(ptr_value)
    return hex(ptr_value)


def ak_singlylinkedlist_summary(valobj, internal_dict):
    valobj = valobj.GetNonSyntheticValue()
    m_head = valobj.GetChildMemberWithName("m_head")

    size = 0
    node = m_head
    while node.GetValueAsUnsigned() != 0:
        size += 1
        next_ptr = node.Dereference().GetChildMemberWithName("next")
        node = next_ptr
        if size > 10000:
            break

    return f"size={size}"


def ak_vector_summary(valobj, internal_dict):
    valobj = valobj.GetNonSyntheticValue()
    m_size = valobj.GetChildMemberWithName("m_size")
    size = m_size.GetValueAsUnsigned()
    return f"size={size}"


class AKVectorSynthProvider:
    def __init__(self, valobj, internal_dict):
        self.valobj = valobj.GetNonSyntheticValue()
        self.update()

    def update(self):
        self.m_size = self.valobj.GetChildMemberWithName("m_size")
        self.size = self.m_size.GetValueAsUnsigned()
        self.elements = []
        self.element_type = None

        if self.size == 0:
            return

        m_metadata = self.valobj.GetChildMemberWithName("m_metadata")
        outline_buffer = m_metadata.GetChildMemberWithName("outline_buffer")

        self.element_type = self.valobj.GetType().GetTemplateArgumentType(0)

        if outline_buffer.GetValueAsUnsigned() != 0:
            elements_ptr = outline_buffer.Cast(self.element_type.GetPointerType())
            self.elements_ptr = elements_ptr
        else:
            inline_buffer = self.valobj.GetChildMemberWithName("m_inline_buffer_storage")
            self.elements_ptr = inline_buffer.Cast(self.element_type.GetPointerType())

    def has_children(self):
        return self.size > 0

    def num_children(self):
        return self.size

    def get_child_index(self, name):
        if name.startswith("[") and name.endswith("]"):
            try:
                return int(name[1:-1])
            except ValueError:
                return -1
        return -1

    def get_child_at_index(self, index):
        if index < 0 or index >= self.size:
            return None
        return self.elements_ptr.CreateChildAtOffset(
            f"[{index}]",
            index * self.element_type.GetByteSize(),
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
        "type summary add -x \"^AK::RefCounted(<.*>)?$\" -F ak.ak_refcounted_summary"
    )
    debugger.HandleCommand(
        "type summary add -x \"^AK::FixedArray(<.*>)?$\" -F ak.ak_fixedarray_summary"
    )
    debugger.HandleCommand(
        "type synthetic add -x \"^AK::FixedArray(<.*>)?$\" -l ak.AKFixedArraySynthProvider"
    )
    debugger.HandleCommand(
        "type summary add -x \"^AK::HashMap(<.*>)?$\" -F ak.ak_hashmap_summary"
    )
    debugger.HandleCommand(
        "type synthetic add -x \"^AK::HashMap(<.*>)?$\" -l ak.AKHashMapSynthProvider"
    )
    debugger.HandleCommand(
        "type summary add -x \"^AK::RefPtr(<.*>)?$\" -F ak.ak_refptr_summary"
    )
    debugger.HandleCommand(
        "type summary add -x \"^AK::OwnPtr(<.*>)?$\" -F ak.ak_ownptr_summary"
    )
    debugger.HandleCommand(
        "type summary add -x \"^AK::NonnullRefPtr(<.*>)?$\" -F ak.ak_nonnullrefptr_summary"
    )
    debugger.HandleCommand(
        "type summary add -x \"^AK::SinglyLinkedList(<.*>)?$\" -F ak.ak_singlylinkedlist_summary"
    )
    debugger.HandleCommand(
        "type synthetic add -x \"^AK::SinglyLinkedList(<.*>)?$\" -l ak.AKSinglyLinkedListSynthProvider"
    )
    debugger.HandleCommand(
        "type summary add -x \"^AK::Vector(<.*>)?$\" -F ak.ak_vector_summary"
    )
    debugger.HandleCommand(
        "type synthetic add -x \"^AK::Vector(<.*>)?$\" -l ak.AKVectorSynthProvider"
    )
