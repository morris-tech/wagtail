function(modal) {
    /* Set up link-types links to open in the modal */
    $('.link-types a', modal.body).click(function() {
        modal.loadUrl(this.href);
        return false;
    });

    /*
    Set up submissions of the search form to open in the modal.

    FIXME: wagtailadmin.views.chooser.browse doesn't actually return a modal-workflow
    response for search queries, so this just fails with a JS error.
    Luckily, the search-as-you-type logic below means that we never actually need to
    submit the form to get search results, so this has the desired effect of preventing
    plain vanilla form submissions from completing (which would clobber the entire
    calling page, not just the modal). It would be nice to do that without throwing
    a JS error, that's all...
    */
    modal.ajaxifyForm($('form.search-form', modal.body));

    /* Set up search-as-you-type behaviour on the search box */
    var searchUrl = $('form.search-form', modal.body).attr('action');

    /* save initial page browser HTML, so that we can restore it if the search box gets cleared */
    var initialPageResultsHtml = $('.collection-results', modal.body).html();

    function search() {
        var query = $('#id_q', modal.body).val();
        if (query != '') {
            $.ajax({
                url: searchUrl,
                data: {
                    q: query,
                    results_only: true
                },
                success: function(data, status) {
                    $('.collection-results', modal.body).html(data);
                    ajaxifySearchResults();
                }
            });
        } else {
            /* search box is empty - restore original page browser HTML */
            $('.collection-results', modal.body).html(initialPageResultsHtml);
            ajaxifyBrowseResults();
        }
        return false;
    }

    $('#id_q', modal.body).on('input', function() {
        clearTimeout($.data(this, 'timer'));
        var wait = setTimeout(search, 200);
        $(this).data('timer', wait);
    });

    /* Set up behaviour of choose-page links in the newly-loaded search results,
    to pass control back to the calling page */
    function ajaxifySearchResults() {
        $('.collection-results a.choose-collection', modal.body).click(function() {
            var pageData = $(this).data();
            modal.respond('collectionChosen', $(this).data());
            modal.close();

            return false;
        });
        /* pagination links within search results should be AJAX-fetched
        and the result loaded into .page-results (and ajaxified) */
        $('.collection-results a.navigate-collections', modal.body).click(function() {
            $('.collection-results', modal.body).load(this.href, ajaxifySearchResults);
            return false;
        });
    }

    function ajaxifyBrowseResults() {
        /* Set up page navigation links to open in the modal */
        $('.collection-results a.navigate-collections', modal.body).click(function() {
            modal.loadUrl(this.href);
            return false;
        });

        /* Set up behaviour of choose-collection links, to pass control back to the calling page */
        $('a.choose-collection', modal.body).click(function() {
            var collectionData = $(this).data();
            collectionData.parentId = {{ parent_collection.id }};
            modal.respond('collectionChosen', $(this).data());
            modal.close();

            return false;
        });
    }
    ajaxifyBrowseResults();

    /*
    Focus on the search box when opening the modal.
    FIXME: this doesn't seem to have any effect (at least on Chrome)
    */
    $('#id_q', modal.body).focus();
}