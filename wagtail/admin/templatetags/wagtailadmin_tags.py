import itertools

from django import template
from django.conf import settings
from django.contrib.humanize.templatetags.humanize import intcomma
from django.contrib.messages.constants import DEFAULT_TAGS as MESSAGE_TAGS
from django.template.defaultfilters import stringfilter
from django.template.loader import render_to_string
from django.utils.html import conditional_escape
from django.utils.safestring import mark_safe

from wagtail.utils.pagination import DEFAULT_PAGE_KEY, replace_page_in_query
from wagtail.admin.menu import admin_menu
from wagtail.admin.navigation import get_explorable_root_page, get_explorable_root_collection
from wagtail.admin.search import admin_search_areas
from wagtail.core import hooks
from wagtail.core.models import (
    Collection, CollectionViewRestriction, Page, PageViewRestriction, UserCollectionPermissionsProxy,
    UserPagePermissionsProxy)
from wagtail.core.utils import cautious_slugify as _cautious_slugify
from wagtail.core.utils import camelcase_to_underscore, escape_script

register = template.Library()

register.filter('intcomma', intcomma)


@register.simple_tag(takes_context=True)
def menu_search(context):
    request = context['request']

    search_areas = admin_search_areas.search_items_for_request(request)
    if not search_areas:
        return ''
    search_area = search_areas[0]

    return render_to_string('wagtailadmin/shared/menu_search.html', {
        'search_url': search_area.url,
    })


@register.inclusion_tag('wagtailadmin/shared/main_nav.html', takes_context=True)
def main_nav(context):
    request = context['request']

    return {
        'menu_html': admin_menu.render_html(request),
        'request': request,
    }


@register.inclusion_tag('wagtailadmin/shared/breadcrumb.html', takes_context=True)
def explorer_breadcrumb(context, page, include_self=False):
    user = context['request'].user

    # find the closest common ancestor of the pages that this user has direct explore permission
    # (i.e. add/edit/publish/lock) over; this will be the root of the breadcrumb
    cca = get_explorable_root_page(user)
    if not cca:
        return {'pages': Page.objects.none()}

    return {
        'pages': page.get_ancestors(inclusive=include_self).descendant_of(cca, inclusive=True)
    }


@register.inclusion_tag('wagtailadmin/collections/breadcrumb.html', takes_context=True)
def collection_breadcrumb(context, collection, include_self=False):
    user = context['request'].user

    # find the closest common ancestor of the collections that this user has direct explore permission
    # (i.e. add/edit/publish/lock) over; this will be the root of the breadcrumb
    cca = get_explorable_root_collection(user)
    if not cca:
        return {'collections': Collection.objects.none()}

    return {
        'collections': collection.get_ancestors(inclusive=include_self).descendant_of(cca, inclusive=True)
    }


@register.inclusion_tag('wagtailadmin/shared/search_other.html', takes_context=True)
def search_other(context, current=None):
    request = context['request']

    return {
        'options_html': admin_search_areas.render_html(request, current),
        'request': request,
    }


@register.simple_tag
def main_nav_js():
    return admin_menu.media['js']


@register.filter("ellipsistrim")
def ellipsistrim(value, max_length):
    if len(value) > max_length:
        truncd_val = value[:max_length]
        if not len(value) == (max_length + 1) and value[max_length + 1] != " ":
            truncd_val = truncd_val[:truncd_val.rfind(" ")]
        return truncd_val + "..."
    return value


@register.filter
def fieldtype(bound_field):
    try:
        return camelcase_to_underscore(bound_field.field.__class__.__name__)
    except AttributeError:
        try:
            return camelcase_to_underscore(bound_field.__class__.__name__)
        except AttributeError:
            return ""


@register.filter
def widgettype(bound_field):
    try:
        return camelcase_to_underscore(bound_field.field.widget.__class__.__name__)
    except AttributeError:
        try:
            return camelcase_to_underscore(bound_field.widget.__class__.__name__)
        except AttributeError:
            return ""


@register.simple_tag(takes_context=True)
def page_permissions(context, page):
    """
    Usage: {% page_permissions page as page_perms %}
    Sets the variable 'page_perms' to a PagePermissionTester object that can be queried to find out
    what actions the current logged-in user can perform on the given page.
    """
    # Create a UserPagePermissionsProxy object to represent the user's global permissions, and
    # cache it in the context for the duration of the page request, if one does not exist already
    if 'user_page_permissions' not in context:
        context['user_page_permissions'] = UserPagePermissionsProxy(context['request'].user)

    # Now retrieve a PagePermissionTester from it, specific to the given page
    return context['user_page_permissions'].for_page(page)


@register.simple_tag(takes_context=True)
def collection_permissions(context, collection):
    """
    Usage: {% collection_permissions collection as collection_perms %}
    Sets the variable 'collection_perms' to a CollectionPermissionTester object that can be queried to find out
    what actions the current logged-in user can perform on the given collection.
    """
    # Create a UserCollectionPermissionsProxy object to represent the user's global permissions, and
    # cache it in the context for the duration of the page request, if one does not exist already
    if 'user_collection_permissions' not in context:
        context['user_collection_permissions'] = UserCollectionPermissionsProxy(context['request'].user)

    # Now retrieve a CollectionPermissionTester from it, specific to the given collection
    return context['user_collection_permissions'].for_collection(collection)


@register.simple_tag(takes_context=True)
def test_collection_is_public(context, collection):
    """
    Usage: {% test_collection_is_public collection as is_public %}
    Sets 'is_public' to True iff there are no collection view restrictions in place
    on this collection.
    Caches the list of collection view restrictions in the context, to avoid repeated
    DB queries on repeated calls.
    """
    if 'all_collection_view_restrictions' not in context:
        context['all_collection_view_restrictions'] = CollectionViewRestriction.objects.select_related('collection').values_list(
            'collection__name', flat=True
        )

    is_private = collection.name in context['all_collection_view_restrictions']

    return not is_private


@register.simple_tag(takes_context=True)
def test_page_is_public(context, page):
    """
    Usage: {% test_page_is_public page as is_public %}
    Sets 'is_public' to True iff there are no page view restrictions in place on
    this page.
    Caches the list of page view restrictions in the context, to avoid repeated
    DB queries on repeated calls.
    """
    if 'all_page_view_restriction_paths' not in context:
        context['all_page_view_restriction_paths'] = PageViewRestriction.objects.select_related('page').values_list(
            'page__path', flat=True
        )

    is_private = any([
        page.path.startswith(restricted_path)
        for restricted_path in context['all_page_view_restriction_paths']
    ])

    return not is_private


@register.simple_tag
def hook_output(hook_name):
    """
    Example: {% hook_output 'insert_editor_css' %}
    Whenever we have a hook whose functions take no parameters and return a string, this tag can be used
    to output the concatenation of all of those return values onto the page.
    Note that the output is not escaped - it is the hook function's responsibility to escape unsafe content.
    """
    snippets = [fn() for fn in hooks.get_hooks(hook_name)]
    return mark_safe(''.join(snippets))


@register.simple_tag
def usage_count_enabled():
    return getattr(settings, 'WAGTAIL_USAGE_COUNT_ENABLED', False)


@register.simple_tag
def base_url_setting():
    return getattr(settings, 'BASE_URL', None)


@register.simple_tag
def allow_unicode_slugs():
    return getattr(settings, 'WAGTAIL_ALLOW_UNICODE_SLUGS', True)


@register.simple_tag
def auto_update_preview():
    return getattr(settings, 'WAGTAIL_AUTO_UPDATE_PREVIEW', False)


class EscapeScriptNode(template.Node):
    TAG_NAME = 'escapescript'

    def __init__(self, nodelist):
        super().__init__()
        self.nodelist = nodelist

    def render(self, context):
        out = self.nodelist.render(context)
        return escape_script(out)

    @classmethod
    def handle(cls, parser, token):
        nodelist = parser.parse(('end' + EscapeScriptNode.TAG_NAME,))
        parser.delete_first_token()
        return cls(nodelist)


register.tag(EscapeScriptNode.TAG_NAME, EscapeScriptNode.handle)


# Helpers for Widget.render_with_errors, our extension to the Django widget API that allows widgets to
# take on the responsibility of rendering their own error messages
@register.filter
def render_with_errors(bound_field):
    """
    Usage: {{ field|render_with_errors }} as opposed to {{ field }}.
    If the field (a BoundField instance) has errors on it, and the associated widget implements
    a render_with_errors method, call that; otherwise, call the regular widget rendering mechanism.
    """
    widget = bound_field.field.widget
    if bound_field.errors and hasattr(widget, 'render_with_errors'):
        return widget.render_with_errors(
            bound_field.html_name,
            bound_field.value(),
            attrs={'id': bound_field.auto_id},
            errors=bound_field.errors
        )
    else:
        return bound_field.as_widget()


@register.filter
def has_unrendered_errors(bound_field):
    """
    Return true if this field has errors that were not accounted for by render_with_errors, because
    the widget does not support the render_with_errors method
    """
    return bound_field.errors and not hasattr(bound_field.field.widget, 'render_with_errors')


@register.filter(is_safe=True)
@stringfilter
def cautious_slugify(value):
    return _cautious_slugify(value)


@register.simple_tag(takes_context=True)
def querystring(context, **kwargs):
    """
    Print out the current querystring. Any keyword arguments to this template
    tag will be added to the querystring before it is printed out.

        <a href="/page/{% querystring key='value' %}">

    Will result in something like:

        <a href="/page/?foo=bar&key=value">
    """
    request = context['request']
    querydict = request.GET.copy()
    # Can't do querydict.update(kwargs), because QueryDict.update() appends to
    # the list of values, instead of replacing the values.
    for key, value in kwargs.items():
        if value is None:
            # Remove the key if the value is None
            querydict.pop(key, None)
        else:
            # Set the key otherwise
            querydict[key] = value

    return '?' + querydict.urlencode()


@register.simple_tag(takes_context=True)
def pagination_querystring(context, page_number, page_key=DEFAULT_PAGE_KEY):
    """
    Print out a querystring with an updated page number:

        {% if page.has_next_page %}
            <a href="{% pagination_link page.next_page_number %}">Next page</a>
        {% endif %}
    """
    return querystring(context, **{page_key: page_number})


@register.inclusion_tag("wagtailadmin/pages/listing/_pagination.html",
                        takes_context=True)
def paginate(context, page, base_url='', page_key=DEFAULT_PAGE_KEY,
             classnames=''):
    """
    Print pagination previous/next links, and the page count. Take the
    following arguments:

    page
        The current page of results. This should be a Django pagination `Page`
        instance

    base_url
        The base URL of the next/previous page, with no querystring.
        This is optional, and defaults to the current page by just printing the
        querystring for the next/previous page.

    page_key
        The name of the page variable in the query string. Defaults to the same
        name as used in the :func:`~wagtail.utils.pagination.paginate`
        function.

    classnames
        Extra classes to add to the next/previous links.
    """
    request = context['request']
    return {
        'base_url': base_url,
        'classnames': classnames,
        'request': request,
        'page': page,
        'page_key': page_key,
        'paginator': page.paginator,
    }


@register.inclusion_tag("wagtailadmin/pages/listing/_buttons.html",
                        takes_context=True)
def page_listing_buttons(context, page, page_perms, is_parent=False):
    button_hooks = hooks.get_hooks('register_page_listing_buttons')
    buttons = sorted(itertools.chain.from_iterable(
        hook(page, page_perms, is_parent)
        for hook in button_hooks))
    return {'page': page, 'buttons': buttons}


@register.inclusion_tag("wagtailadmin/pages/listing/_buttons.html",
                        takes_context=True)
def collection_listing_buttons(context, collection, is_parent=False):
    button_hooks = hooks.get_hooks('register_collection_listing_buttons')
    collection_perms = collection.permissions_for_user(context['request'].user)
    buttons = sorted(itertools.chain.from_iterable(
        hook(collection, collection_perms, is_parent)
        for hook in button_hooks))
    return {'collection': collection, 'buttons': buttons}


@register.simple_tag
def message_tags(message):
    level_tag = MESSAGE_TAGS.get(message.level)
    if message.extra_tags and level_tag:
        return message.extra_tags + ' ' + level_tag
    elif message.extra_tags:
        return message.extra_tags
    elif level_tag:
        return level_tag
    else:
        return ''


@register.simple_tag
def replace_page_param(query, page_number, page_key='p'):
    """
    Replaces ``page_key`` from query string with ``page_number``.
    """
    return conditional_escape(replace_page_in_query(query, page_number, page_key))


@register.filter('abs')
def _abs(val):
    return abs(val)


@register.inclusion_tag('wagtailadmin/shared/collection_chooser.html', takes_context=True)
def collection_chooser(context, collections, label='Collection', selected_collection=None, show_all_collections=True,
                       field_name='collection_id', enable_widget_mode=False):
    """
    Render the select field for choosing a collection. Represents the hierarchy by prefixing the names with `--`.

    Takes the following params:

    collections
        The iterable of collections that should be displayed to the user.

    label
        The label that should be shown next to the select field.

    selected_collection
        The primary key of the collection that should be used as the selected value.

    show_all_collections
        Whether or not the "All collections" option should be shown.

    field_name
        The value to use for the `name` attribute on the collection field.

    enable_widget_mode
        Used when rendering the collection options from the collection admin widget. When True, the label
        and html surrounding the select field will be removed.

    """
    choices = []
    for collection in collections:
        name_prefix = ''
        if collection.depth > 1:
            name_prefix = '--' * (collection.depth - 1)
        collection_name = '{depth_marks} {name}'.format(depth_marks=name_prefix, name=collection.name)
        choices.append((collection.pk, collection_name))

    # Attempt to convert selected_collection to an int
    if selected_collection is not None and not isinstance(selected_collection, int):
        if not isinstance(selected_collection, str) and len(selected_collection) == 1:
            selected_collection = selected_collection[0]

        try:
            selected_collection = int(selected_collection)
        except ValueError:
            pass

    context.update({
        'collection_choices': choices,
        'selected_collection': selected_collection,
        'label': label,
        'show_all_collections': show_all_collections,
        'field_name': field_name,
        'enable_widget_mode': enable_widget_mode,
    })
    return context