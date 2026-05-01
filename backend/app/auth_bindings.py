def create_auth_bindings(
    *,
    auth_utils,
    db_module,
    device_tokens_db: str,
    device_tokens_file: str,
    local_networks,
    admin_password: str,
    manager_password: str,
    viewer_password: str,
    dashboard_public: bool,
    legacy_query_auth_enabled: bool = False,
    legacy_basic_auth_enabled: bool = False,
):
    def load_device_tokens():
        return auth_utils.load_device_tokens(
            db_module=db_module,
            device_tokens_db=device_tokens_db,
            device_tokens_file=device_tokens_file,
        )

    def save_device_tokens(tokens):
        return auth_utils.save_device_tokens(
            tokens=tokens,
            db_module=db_module,
            device_tokens_db=device_tokens_db,
            device_tokens_file=device_tokens_file,
        )

    def generate_device_token(user_agent: str, client_ip: str) -> str:
        return auth_utils.generate_device_token(user_agent, client_ip)

    def is_device_token_valid(token: str) -> bool:
        return auth_utils.is_device_token_valid(
            token=token,
            load_tokens=load_device_tokens,
            save_tokens=save_device_tokens,
        )

    def touch_device_token(token: str, client_ips: list | None = None, user_agent: str | None = None):
        return auth_utils.touch_device_token(
            token=token,
            load_tokens=load_device_tokens,
            save_tokens=save_device_tokens,
            client_ips=client_ips,
            user_agent=user_agent,
        )

    def is_local_network(client_ip: str) -> bool:
        return auth_utils.is_local_network(client_ip=client_ip, local_networks=local_networks)

    def get_client_ip(request):
        return auth_utils.get_client_ip(request)

    def get_client_ips(request):
        return auth_utils.get_client_ips(request)

    def get_role_from_request(request):
        return auth_utils.get_role_from_request(
            request=request,
            admin_password=admin_password,
            manager_password=manager_password,
            viewer_password=viewer_password,
            is_token_valid=is_device_token_valid,
            load_tokens=load_device_tokens,
        )

    def require_manager_or_admin(request):
        return auth_utils.require_manager_or_admin(request=request, get_role=get_role_from_request)

    def require_admin(request):
        return auth_utils.require_admin(request=request, get_role=get_role_from_request)

    async def auth_middleware(request, call_next):
        return await auth_utils.auth_middleware(
            request=request,
            call_next=call_next,
            dashboard_public=dashboard_public,
            admin_password=admin_password,
            manager_password=manager_password,
            viewer_password=viewer_password,
            is_local_network_fn=is_local_network,
            is_token_valid_fn=is_device_token_valid,
            load_tokens_fn=load_device_tokens,
            touch_token_fn=touch_device_token,
            get_client_ip_fn=get_client_ip,
            get_client_ips_fn=get_client_ips,
            legacy_query_auth_enabled=legacy_query_auth_enabled,
            legacy_basic_auth_enabled=legacy_basic_auth_enabled,
        )

    return {
        "load_device_tokens": load_device_tokens,
        "save_device_tokens": save_device_tokens,
        "generate_device_token": generate_device_token,
        "is_device_token_valid": is_device_token_valid,
        "touch_device_token": touch_device_token,
        "is_local_network": is_local_network,
        "get_client_ip": get_client_ip,
        "get_client_ips": get_client_ips,
        "get_role_from_request": get_role_from_request,
        "require_manager_or_admin": require_manager_or_admin,
        "require_admin": require_admin,
        "auth_middleware": auth_middleware,
    }
