class THESAGRAError(Exception):
    code = "THESAGRA_ERROR"


class ConnectionError(THESAGRAError):
    code = "CONNECTION_ERROR"


class AuthenticationError(THESAGRAError):
    code = "AUTH_FAILED"


class QueryError(THESAGRAError):
    code = "QUERY_ERROR"


class ProtocolError(THESAGRAError):
    code = "PROTOCOL_ERROR"


class CancelledError(THESAGRAError):
    code = "CANCELLED"


class BlobError(THESAGRAError):
    code = "BLOB_ERROR"


class GraphError(THESAGRAError):
    code = "GRAPH_ERROR"
