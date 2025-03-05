@require_loggedin_user()
def get_asset_icon(asset_identifier: str) -> Response:
    """
    Get the icon for an asset
    """
    try:
        result = {'result': get_asset_icon_path(asset_identifier)}
        return api_response(result=result, status_code=HTTPStatus.OK)
    except (UnknownAsset, IconError) as e:
        return api_response(wrap_in_fail_result(str(e)), status_code=HTTPStatus.BAD_REQUEST)


class AssetOraclePreferenceSchema(Schema):
    asset = AssetField(required=True)
    current_price_oracle = fields.Nested(CurrentPriceOracleSchema, required=False, missing=None)
    historical_price_oracle = fields.Nested(HistoricalPriceOracleSchema, required=False, missing=None)


@require_loggedin_user()
def set_asset_oracle_preference(
        asset: Asset,
        current_price_oracle: CurrentPriceOracle | None = None,
        historical_price_oracle: HistoricalPriceOracle | None = None,
) -> Response:
    """
    Set the preferred oracle for an asset
    """
    try:
        GlobalDBHandler.set_asset_oracle_preference(
            asset_identifier=asset.identifier,
            current_price_oracle=current_price_oracle,
            historical_price_oracle=historical_price_oracle,
        )
        return api_response(result=True, status_code=HTTPStatus.OK)
    except UnknownAsset as e:
        return api_response(wrap_in_fail_result(str(e)), status_code=HTTPStatus.BAD_REQUEST)


@require_loggedin_user()
def get_asset_oracle_preference(asset: Asset) -> Response:
    """
    Get the preferred oracle for an asset
    """
    try:
        current_oracle, historical_oracle = GlobalDBHandler.get_asset_oracle_preference(
            asset_identifier=asset.identifier,
        )
        result = {
            'current_price_oracle': current_oracle.name if current_oracle else None,
            'historical_price_oracle': historical_oracle.name if historical_oracle else None,
        }
        return api_response(result=result, status_code=HTTPStatus.OK)
    except UnknownAsset as e:
        return api_response(wrap_in_fail_result(str(e)), status_code=HTTPStatus.BAD_REQUEST)


@require_loggedin_user()
def delete_asset_oracle_preference(asset: Asset) -> Response:
    """
    Delete the preferred oracle for an asset
    """
    try:
        GlobalDBHandler.delete_asset_oracle_preference(asset_identifier=asset.identifier)
        return api_response(result=True, status_code=HTTPStatus.OK)
    except UnknownAsset as e:
        return api_response(wrap_in_fail_result(str(e)), status_code=HTTPStatus.BAD_REQUEST) 